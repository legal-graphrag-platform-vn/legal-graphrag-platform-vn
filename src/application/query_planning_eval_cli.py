"""Run the read-only QG-1 development evaluation against Neo4j and Gemini."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Sequence

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.application.gemini_query_planner import GeminiQueryPlanner
from src.application.retrieval_factory import (
    RetrievalApplicationSettings,
    SystemClock,
)
from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator
from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.config import EndpointLinkerConfig, RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.eval.query_graph_qg0 import load_gold_plan_config
from src.retrieval.eval.query_planning import (
    QG1Metadata,
    QG1ObservationCollector,
    RuleBasedPlannerBaseline,
    evaluate_qg1,
    load_qg1_thresholds,
    write_qg1_artifacts,
)
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.planning.config import QueryPlannerConfig
from src.retrieval.planning.executor import PlannedPathExecutor
from src.retrieval.planning.linker import (
    EndpointLinker,
    SemanticEndpointResolver,
    StructuralEndpointResolver,
)
from src.retrieval.planning.prompts import build_query_planner_request
from src.retrieval.retriever.fulltext import FullTextRetriever
from src.retrieval.retriever.graph import GraphRetriever
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.retriever.vector import VectorRetriever
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.runtime import RetrievalRuntime


class _ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    gemini_api_key: str = Field(validation_alias="GEMINI_API_KEY")
    query_planner_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="QUERY_PLANNER_MODEL",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.application.query_planning_eval_cli"
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("configs/evaluation/query_graph_gold_plans.json"),
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("configs/evaluation/query_graph_generation_thresholds.json"),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("results/retrieval/query_graph_qg1.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("results/retrieval/query_graph_qg1.md"),
    )
    parser.add_argument("--graph-snapshot-hash", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    gold = load_gold_plan_config(args.gold)
    thresholds = load_qg1_thresholds(args.thresholds)
    retrieval_settings = RetrievalApplicationSettings()
    provider_settings = _ProviderSettings()
    runtime_config = RetrievalConfig()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        retrieval_settings.neo4j_uri,
        auth=(
            retrieval_settings.neo4j_user,
            retrieval_settings.neo4j_password,
        ),
    )
    planner = GeminiQueryPlanner(
        api_key=provider_settings.gemini_api_key,
        model=provider_settings.query_planner_model,
        config=QueryPlannerConfig(timeout_seconds=60, max_retries=1),
    )
    try:
        driver.verify_connectivity()
        repo = Neo4jRetrieverRepo(driver)
        embedding = EmbeddingGenerator(
            model_name=retrieval_settings.embedding_model,
            provider=retrieval_settings.embedding_provider,
            expected_dimension=retrieval_settings.embedding_dimension,
            normalize_embeddings=True,
        )
        vector = VectorRetriever(repo, embedding)
        fulltext = FullTextRetriever(repo)
        executor = PlannedPathExecutor(repo)
        linker = EndpointLinker(
            structural=StructuralEndpointResolver(repo),
            semantic=SemanticEndpointResolver(
                vector=vector,
                fulltext=fulltext,
                config=EndpointLinkerConfig(),
            ),
        )
        runtime = RetrievalRuntime(
            router=IntentRouter(runtime_config, clock=SystemClock()),
            seed_executor=SeedChannelExecutor(vector=vector, fulltext=fulltext),
            graph_retriever=GraphRetriever(repo),
            capability_inspector=repo,
            fusion=ReciprocalRankFusion(runtime_config.rrf_k),
            temporal_filter=TemporalFilter(),
            context_builder=ContextBuilder(EvidenceVerifier()),
            planned_executor=executor,
        )
        observations = await QG1ObservationCollector(
            generic_runtime=runtime,
            linker=linker,
            executor=executor,
            llm_planner=planner,
            rule_based_planner=RuleBasedPlannerBaseline(),
        ).collect(gold)
        report = evaluate_qg1(
            gold,
            thresholds,
            observations,
            metadata=QG1Metadata(
                graph_snapshot_sha256=args.graph_snapshot_hash,
                planner_provider=planner.provider_name,
                planner_model=planner.model_name,
                prompt_fingerprint=_prompt_fingerprint(),
            ),
        )
        write_qg1_artifacts(
            report,
            json_path=args.json_output,
            markdown_path=args.markdown_output,
        )
        return 0
    finally:
        await planner.aclose()
        driver.close()


def _prompt_fingerprint() -> str:
    request = build_query_planner_request("__QG1_QUERY_PLACEHOLDER__")
    payload = json.dumps(
        {
            "system_instruction": request.system_instruction,
            "prompt_template": request.prompt,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
