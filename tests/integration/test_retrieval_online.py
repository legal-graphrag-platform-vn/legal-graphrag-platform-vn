import hashlib
import json
from datetime import date

import pytest
from neo4j import GraphDatabase

from main import create_app
from settings import Settings as BackendSettings
from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.pipeline.config import settings
from src.retrieval.config import RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import RetrievalFilters, RetrievalRequest
from src.retrieval.retriever.fulltext import FullTextRetriever
from src.retrieval.retriever.graph import GraphRetriever
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.retriever.vector import VectorRetriever
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.runtime import RetrievalRuntime
from tests.asgi_client import SyncASGIClient


pytestmark = [pytest.mark.integration, pytest.mark.retrieval_readonly]


class FixedEmbedding:
    def __init__(self, embedding: list[float]) -> None:
        self._embedding = embedding

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self._embedding for _ in texts]


class FixedClock:
    def today(self) -> date:
        return date(2026, 7, 13)


def test_runtime_retrieval_does_not_mutate_pilot() -> None:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            seed = session.run(
                """
                MATCH (d:Document)-[:CONTAINS*1..3]->(a:Article)
                WHERE a.embedding IS NOT NULL
                RETURN d.id AS document_id, a.embedding AS embedding
                ORDER BY d.id, a.id
                LIMIT 1
                """
            ).single()
        if seed is None:
            pytest.skip("Disposable database has no embedded pilot document")

        document_id = str(seed["document_id"])
        before = _pilot_digests(driver, document_id)
        repo = Neo4jRetrieverRepo(driver)
        capabilities = repo.inspect_capabilities(
            RetrievalFilters(document_ids=[document_id])
        )
        assert capabilities["scoped_temporal_metadata_available"] is True
        assert capabilities["structural_hierarchy_available"] is True
        assert capabilities["semantic_multi_hop_graph_available"] is True
        assert capabilities["corpus_complete_current_validity_available"] is False
        assert capabilities["guides_relations_available"] is False
        assert capabilities["multiple_versions_available"] is False
        config = RetrievalConfig()
        runtime = RetrievalRuntime(
            router=IntentRouter(config, clock=FixedClock()),
            seed_executor=SeedChannelExecutor(
                vector=VectorRetriever(repo, FixedEmbedding(list(seed["embedding"]))),
                fulltext=FullTextRetriever(repo),
            ),
            graph_retriever=GraphRetriever(repo),
            capability_inspector=repo,
            fusion=ReciprocalRankFusion(config.rrf_k),
            temporal_filter=TemporalFilter(),
            context_builder=ContextBuilder(EvidenceVerifier()),
        )
        context = runtime.retrieve(
            RetrievalRequest(
                query="quyền thành lập và quản lý doanh nghiệp",
                filters=RetrievalFilters(document_ids=[document_id]),
                final_k=5,
            )
        )
        after = _pilot_digests(driver, document_id)

        assert context.retrieved_units
        assert all(unit.document_id == document_id for unit in context.retrieved_units)
        assert before == after
    finally:
        driver.close()


def test_backend_query_api_preserves_read_only_pilot_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            seed = session.run(
                """
                MATCH (document:Document)-[:CONTAINS*1..3]->(unit)
                WHERE unit:Article OR unit:Clause
                RETURN document.id AS document_id
                ORDER BY document.id
                LIMIT 1
                """
            ).single()
        if seed is None:
            pytest.skip("Disposable database has no pilot document")

        document_id = str(seed["document_id"])
        before = _pilot_digests(driver, document_id)
        monkeypatch.setenv("RETRIEVAL_VECTOR_ENABLED", "false")
        monkeypatch.setenv("RETRIEVAL_FULLTEXT_ENABLED", "true")
        monkeypatch.setenv("RETRIEVAL_GRAPH_ENABLED", "true")
        monkeypatch.setenv("RETRIEVAL_RERANKER_ENABLED", "false")
        app = create_app(
            BackendSettings(
                app_mode="graphrag",
                neo4j_uri=settings.neo4j_uri,
                neo4j_user=settings.neo4j_user,
                neo4j_password=settings.neo4j_password,
                _env_file=None,
            )
        )
        with SyncASGIClient(app) as client:
            response = client.post(
                "/api/v1/query",
                json={
                    "query": "quyền thành lập doanh nghiệp",
                    "document_ids": [document_id],
                    "top_k": 5,
                    "candidate_k": 10,
                },
            )
        after = _pilot_digests(driver, document_id)

        assert response.status_code == 200
        payload = response.json()
        assert payload["retrieved_units"]
        assert all(
            unit["document_id"] == document_id for unit in payload["retrieved_units"]
        )
        assert "answer" not in payload
        assert before == after
    finally:
        driver.close()


def _pilot_digests(driver, document_id: str) -> tuple[str, str]:
    with driver.session() as session:
        node_rows = list(
            session.run(
                """
                MATCH (d:Document {id: $document_id})
                OPTIONAL MATCH (d)-[:CONTAINS*0..3]->(node)
                RETURN DISTINCT node.id AS id, labels(node) AS labels,
                       properties(node) AS properties
                ORDER BY id
                """,
                document_id=document_id,
            )
        )
        node_ids = [str(row["id"]) for row in node_rows if row["id"]]
        relation_rows = list(
            session.run(
                """
                MATCH (source)-[relation]->(target)
                WHERE source.id IN $node_ids AND target.id IN $node_ids
                RETURN source.id AS source_id, type(relation) AS type,
                       target.id AS target_id, properties(relation) AS properties
                ORDER BY source_id, type, target_id, relation.relation_id
                """,
                node_ids=node_ids,
            )
        )
    legal_nodes = []
    embedding_nodes = []
    for row in node_rows:
        properties = dict(row["properties"] or {})
        embedding_state = {
            key: properties.pop(key)
            for key in list(properties)
            if key.startswith("embedding")
        }
        legal_nodes.append((row["id"], list(row["labels"]), properties))
        embedding_nodes.append((row["id"], embedding_state))
    legal = _digest(
        {
            "nodes": legal_nodes,
            "relations": [
                (
                    row["source_id"],
                    row["type"],
                    row["target_id"],
                    dict(row["properties"] or {}),
                )
                for row in relation_rows
            ],
        }
    )
    return legal, _digest(embedding_nodes)


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
