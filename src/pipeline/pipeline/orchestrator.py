"""Pipeline Orchestrator — nối Parser -> LLM Extraction -> Schema/Ontology Validation
-> Confidence Scoring -> Decision Gate.

Phạm vi M1+M2: dừng ở ghi accepted/review/rejected JSONL — KHÔNG ghi Neo4j, KHÔNG
tạo embedding (Milestone 3, ngoài phạm vi task hiện tại).

LƯU Ý GIỚI HẠN: `GUIDES` cần `head_doc_type`/`tail_doc_type` của ĐÚNG
văn bản được tham chiếu (vd Decree mà Article này dẫn tới), nhưng ở M1+M2 chưa có
document registry (đó là việc của Neo4j/M3) nên orchestrator chỉ suy ra doc_type khi
entity type là chính document đang xử lý; còn lại doc_type=None -> validator reject
-> relation rơi vào review queue thay vì bị auto-accept sai. Đây là hành vi an
toàn có chủ đích, không phải bug.
"""

from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
import re
import unicodedata

from src.pipeline.config import settings
from src.pipeline.extraction.llm_extractor import extract_article
from src.pipeline.extraction.models import ExtractedEntity
from src.pipeline.extraction.models import ExtractionResult
from src.pipeline.extraction.providers.base import ExtractionProviderError
from src.pipeline.extraction.structural_context import (
    ENDPOINT_CONTRACT_VERSION,
    PROMPT_VERSION,
    DocumentRegistry,
    EndpointResolution,
    StructuralRegistry,
)
from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument
from src.pipeline.scoring.confidence_scorer import score
from src.shared.ontology.validators import validate_relation as validate_ontology
from src.pipeline.validation.record_consistency_validator import validate_record_relation
from src.pipeline.validation.schema_validator import validate_relation as validate_schema

logger = logging.getLogger(__name__)


def _entity_type_lookup(entities: list[ExtractedEntity]) -> dict[str, str]:
    return {e.id: e.type for e in entities}


def _ontology_label(extraction_label: str) -> str:
    return {
        "Entity": "LegalSubject",
        "Concept": "LegalConcept",
        "Action": "LegalAction",
    }.get(extraction_label, extraction_label)


def _semantic_id(label: str) -> str:
    normalized = unicodedata.normalize("NFD", label)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "unknown"


def _entity_index_entry(entity: ExtractedEntity) -> dict | None:
    node_type = _ontology_label(entity.type)
    if node_type not in {"LegalConcept", "LegalSubject", "LegalAction"}:
        return None
    return {
        "id": _semantic_id(entity.label),
        "type": node_type,
        "label": entity.label,
        "name": entity.label,
        "aliases": [],
        "description": None,
    }


def _resolve_endpoint(
    raw_id: str,
    entity_types: dict[str, str],
    entities: list[ExtractedEntity],
    semantic_entries: dict[str, dict],
    registry: StructuralRegistry,
    document_registry: DocumentRegistry,
    article_number: str,
) -> EndpointResolution:
    if raw_id in semantic_entries:
        entry = semantic_entries[raw_id]
        return EndpointResolution(
            raw_id=raw_id,
            canonical_id=entry["id"],
            canonical_type=entry["type"],
            status="resolved",
            method="semantic_entity_index",
        )

    entity = next((candidate for candidate in entities if candidate.id == raw_id), None)
    entity_type = entity_types.get(raw_id)
    resolution = registry.resolve(
        raw_id,
        current_article=article_number,
        entity_type=entity_type,
        entity_label=entity.label if entity else None,
    )
    if resolution.status == "resolved":
        return resolution
    if entity_type == "Document":
        external = document_registry.resolve(raw_id, entity.label if entity else None)
        if external:
            graph_id, _ = external
            return EndpointResolution(
                raw_id,
                graph_id,
                "Document",
                "review",
                "document_registry",
                "external_document_requires_registry_lookup",
            )
        return EndpointResolution(
            raw_id=raw_id,
            canonical_id=None,
            canonical_type="Document",
            status="review",
            method="document_registry",
            reason="missing_external_document_registry",
        )
    return resolution


def _resolution_dict(resolution: EndpointResolution) -> dict:
    return {
        "raw_id": resolution.raw_id,
        "canonical_id": resolution.canonical_id,
        "canonical_type": resolution.canonical_type,
        "status": resolution.status,
        "method": resolution.method,
        "reason": resolution.reason,
    }


def _configured_llm_model() -> str:
    provider = settings.llm_provider.lower()
    model_by_provider = {
        "gemini": settings.gemini_model,
        "minimax": settings.minimax_model,
        "qwen": settings.qwen_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }
    model = model_by_provider.get(provider, "")
    return f"{provider}:{model}" if model else provider


def _relation_properties(raw_relation, article: Article, document: DocumentInfo) -> dict:
    relation_properties = {}
    created_at = datetime.now(timezone.utc).isoformat()

    if raw_relation.relation in {"AMENDS", "REPEALS", "REPLACES"} and document.effective_from:
        relation_properties["effective_from"] = str(document.effective_from)
    if raw_relation.relation == "AMENDS":
        relation_properties["source_doc_id"] = document.id
    if raw_relation.relation == "REFERS_TO":
        relation_properties["citation_text"] = raw_relation.evidence
        relation_properties["citation_type"] = "DIRECT"
    if raw_relation.relation in {"DEFINES", "REGULATES", "REQUIRES"}:
        relation_properties["confidence"] = raw_relation.confidence
        relation_properties["llm_model"] = _configured_llm_model()
        relation_properties["created_at"] = created_at
    if raw_relation.relation == "REQUIRES":
        relation_properties["source_article"] = f"{document.id}_art{article.number}"

    return relation_properties


def process_article(
    article: Article,
    document: DocumentInfo,
    all_records: list[dict],
    entity_index: dict[str, dict] | None = None,
    *,
    registry: StructuralRegistry | None = None,
    extraction_result: ExtractionResult | None = None,
    document_registry: DocumentRegistry | None = None,
) -> int:
    """Chạy Pass 1+2 extraction + validation + scoring cho 1 Article. Trả về số relations xử lý."""
    article_text = article.content_raw
    registry = registry or StructuralRegistry.from_parsed_document(
        ParsedDocument(document=document, articles=[article]), raw_doc_code=document.id
    )
    context = registry.context_for_article(article)
    document_registry = document_registry or DocumentRegistry.from_manifest(settings.curated_manifest_path)
    result = extraction_result or extract_article(article.number, article_text, context=context)

    entity_types = _entity_type_lookup(result.entities)
    if entity_index is not None:
        for entity in result.entities:
            entry = _entity_index_entry(entity)
            if entry:
                existing = entity_index.get(entry["id"])
                if existing is not None and existing != entry:
                    raise ValueError(f"Conflicting semantic entity normalization: {entry['id']}")
                entity_index[entry["id"]] = entry

    semantic_entries: dict[str, dict] = {}
    for entity in result.entities:
        entry = _entity_index_entry(entity)
        if entry:
            semantic_entries[entity.id] = entry
    known_ids = set(registry.types) | {entry["id"] for entry in semantic_entries.values()}

    for raw_relation in result.relations:
        raw_relation_dict = raw_relation.model_dump()
        head_resolution = _resolve_endpoint(
            raw_relation.head, entity_types, result.entities, semantic_entries, registry, document_registry, article.number
        )
        tail_resolution = _resolve_endpoint(
            raw_relation.tail, entity_types, result.entities, semantic_entries, registry, document_registry, article.number
        )
        relation_dict = raw_relation.model_dump()
        if head_resolution.canonical_id:
            relation_dict["head"] = head_resolution.canonical_id
        if tail_resolution.canonical_id:
            relation_dict["tail"] = tail_resolution.canonical_id
        parsed_relation, schema_err = validate_schema(relation_dict)
        schema_valid = parsed_relation is not None

        head_type = head_resolution.canonical_type or _ontology_label(entity_types.get(raw_relation.head, "Entity"))
        tail_type = tail_resolution.canonical_type or _ontology_label(entity_types.get(raw_relation.tail, "Entity"))
        head_doc_type = document.doc_type if head_type == "Document" else None
        tail_doc_type = document.doc_type if tail_type == "Document" else None

        # 1.   Construct actual relationship properties from document metadata and context
        relation_properties = _relation_properties(raw_relation, article, document)

        # 2.   Enrich the relation dictionary with actual properties
        relation_dict["properties"] = relation_properties

        if raw_relation.relation == "CONTAINS":
            ontology_ok, ontology_err = False, "llm_structural_relation_forbidden"
        elif head_resolution.status == "rejected" or tail_resolution.status == "rejected":
            ontology_ok, ontology_err = False, head_resolution.reason or tail_resolution.reason
        else:
            ontology_ok, ontology_err = validate_ontology(
                head_type,
                raw_relation.relation,
                tail_type,
                head_id=relation_dict["head"],
                tail_id=relation_dict["tail"],
                properties=relation_properties,
                head_doc_type=head_doc_type,
                tail_doc_type=tail_doc_type,
            )

        consistency = validate_record_relation(
            relation_type=raw_relation.relation,
            head_id=relation_dict["head"],
            tail_id=relation_dict["tail"],
            properties=relation_properties,
            known_entity_ids=known_ids,
            ontology_valid=ontology_ok,
            head_type=head_type,
            tail_type=tail_type,
        )

        breakdown = score(
            schema_valid=schema_valid,
            ontology_valid=ontology_ok,
            evidence=raw_relation.evidence,
            article_text=article_text,
            head_id=relation_dict["head"],
            tail_id=relation_dict["tail"],
            known_entity_ids=known_ids,
        )

        record = {
            "document_id": document.id,
            "article_number": article.number,
            "raw_relation": raw_relation_dict,
            "relation": relation_dict,
            "endpoint_resolution": {
                "head": _resolution_dict(head_resolution),
                "tail": _resolution_dict(tail_resolution),
            },
            "schema_valid": schema_valid,
            "schema_error": schema_err,
            "ontology_valid": ontology_ok,
            "ontology_error": ontology_err,
            "consistency_valid": consistency.valid,
            "consistency_error": consistency.error,
            "review_reason": consistency.review_reason,
            "blocking": consistency.blocking,
            "confidence": breakdown.total,
        }
        all_records.append(record)

    return len(result.relations)


def _process_article_worker(
    article: Article,
    document: DocumentInfo,
    registry: StructuralRegistry,
    document_registry: DocumentRegistry,
    checkpoint: dict | None = None,
) -> tuple[list[dict], dict[str, dict], dict]:
    records = []
    entity_index: dict[str, dict] = {}
    context = registry.context_for_article(article)
    result = _result_from_checkpoint(checkpoint) if checkpoint else extract_article(
        article.number, article.content_raw, context=context
    )
    process_article(
        article,
        document,
        records,
        entity_index,
        registry=registry,
        extraction_result=result,
        document_registry=document_registry,
    )
    return records, entity_index, _checkpoint_row(result, context, article.content_raw)


def run_pipeline(
    parsed: ParsedDocument,
    processed_dir: Path,
    *,
    raw_doc_code: str,
    provider_calls_allowed: bool = True,
    article_numbers: set[str] | None = None,
) -> None:
    if not raw_doc_code:
        raise ValueError("raw_doc_code is required for pipeline output path")

    out_dir = processed_dir / raw_doc_code
    out_dir.mkdir(parents=True, exist_ok=True)
    
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    all_records = []
    entity_index: dict[str, dict] = {}
    registry = StructuralRegistry.from_parsed_document(parsed, raw_doc_code)
    selected_articles = [
        article for article in parsed.articles if article_numbers is None or article.number in article_numbers
    ]
    if article_numbers is not None:
        found = {article.number for article in selected_articles}
        missing_selection = sorted(article_numbers - found)
        if missing_selection:
            raise ValueError(f"Selected Article(s) not found in hierarchy: {missing_selection}")
    if not selected_articles:
        raise ValueError("Extraction requires at least one selected Article")
    document_registry = DocumentRegistry.from_manifest(settings.curated_manifest_path)
    checkpoint_path = out_dir / "article_extractions.jsonl"
    checkpoints = _load_checkpoints(checkpoint_path, registry, parsed)
    if not provider_calls_allowed:
        missing = [article.number for article in selected_articles if article.number not in checkpoints]
        if missing:
            raise ValueError(f"Missing valid Article extraction checkpoints: {missing[:10]}")
    max_workers = settings.extraction_max_workers
    logger.info("Bắt đầu trích xuất tri thức song song với %d workers...", max_workers)

    results_by_article = {}
    articles = iter(selected_articles)
    total = len(selected_articles)
    completed = 0
    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_to_article = {}

    def submit_next() -> bool:
        article = next(articles, None)
        if article is None:
            return False
        checkpoint = checkpoints.get(article.number)
        future = executor.submit(
            _process_article_worker, article, parsed.document, registry, document_registry, checkpoint
        )
        future_to_article[future] = article
        return True

    for _ in range(min(max_workers, total)):
        submit_next()

    try:
        while future_to_article:
            done, _ = wait(tuple(future_to_article), return_when=FIRST_COMPLETED)
            for future in done:
                article = future_to_article.pop(future)
                try:
                    records, article_entity_index, checkpoint_row = future.result()
                except Exception as exc:
                    for pending in future_to_article:
                        pending.cancel()
                    _write_extraction_blocked(out_dir, exc)
                    logger.error("Extraction blocked at Điều %s: %s", article.number, exc)
                    if isinstance(exc, ExtractionProviderError):
                        raise
                    raise RuntimeError(f"Extraction failed at Article {article.number}: {exc}") from exc

                completed += 1
                results_by_article[article.number] = records
                entity_index.update(article_entity_index)
                existing_models = {
                    row.get("resolved_model") for row in checkpoints.values() if row.get("resolved_model")
                }
                if checkpoint_row.get("resolved_model") and existing_models and checkpoint_row["resolved_model"] not in existing_models:
                    error = RuntimeError(
                        "Resolved model changed within extraction checkpoints: "
                        f"existing={sorted(existing_models)}, new={checkpoint_row['resolved_model']}"
                    )
                    _write_extraction_blocked(out_dir, error)
                    raise error
                checkpoints[article.number] = checkpoint_row
                _write_checkpoints(checkpoint_path, checkpoints)
                logger.info("Đã trích xuất xong Điều %s (%d/%d)", article.number, completed, total)
                submit_next()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    # Đảm bảo giữ đúng thứ tự các Điều trong văn bản gốc
    for article in selected_articles:
        if article.number in results_by_article:
            all_records.extend(results_by_article[article.number])

    all_records = [_apply_decision_gate(record) for record in all_records]

    # 1. Ghi tất cả ra file extract.jsonl (mỗi dòng 1 bản ghi JSON)
    extract_jsonl_path = out_dir / "extract.jsonl"
    _write_jsonl(extract_jsonl_path, all_records)

    # 2. Ghi ra file prettier_extract.json (định dạng đẹp, dễ đọc)
    prettier_json_path = out_dir / "prettier_extract.json"
    with prettier_json_path.open("w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2, default=str)

    _write_jsonl(out_dir / "accepted.jsonl", [record for record in all_records if record["decision"] == "accepted"])
    _write_jsonl(out_dir / "review.jsonl", [record for record in all_records if record["decision"] == "review"])
    _write_jsonl(out_dir / "rejected.jsonl", [record for record in all_records if record["decision"] == "rejected"])
    (out_dir / "entity_index.json").write_text(
        json.dumps(entity_index, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / "extraction_run.json").write_text(
        json.dumps(
            {
                "raw_doc_code": raw_doc_code,
                "graph_id": parsed.document.id,
                "selected_articles": [article.number for article in selected_articles],
                "document_article_count": len(parsed.articles),
                "complete_document": len(selected_articles) == len(parsed.articles),
                "prompt_version": PROMPT_VERSION,
                "endpoint_contract_version": ENDPOINT_CONTRACT_VERSION,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "extraction_blocked.json").unlink(missing_ok=True)


def _checkpoint_fingerprint(context, article_text: str) -> str:
    source = "|".join(
        [
            context.to_prompt_json(),
            article_text,
            settings.llm_provider,
            _configured_llm_model(),
            PROMPT_VERSION,
            ENDPOINT_CONTRACT_VERSION,
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _checkpoint_row(result: ExtractionResult, context, article_text: str) -> dict:
    return {
        "raw_doc_code": context.raw_doc_code,
        "graph_id": context.graph_id,
        "article_number": context.article_number,
        "fingerprint": _checkpoint_fingerprint(context, article_text),
        "provider": settings.llm_provider,
        "configured_model": _configured_llm_model(),
        "resolved_model": result.resolved_model,
        "prompt_version": PROMPT_VERSION,
        "endpoint_contract_version": ENDPOINT_CONTRACT_VERSION,
        "content_hash": hashlib.sha256(article_text.encode("utf-8")).hexdigest(),
        "raw_entities": [entity.model_dump() for entity in result.raw_entities],
        "entities": [entity.model_dump() for entity in result.entities],
        "relations": [relation.model_dump() for relation in result.relations],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def _result_from_checkpoint(row: dict | None) -> ExtractionResult:
    if not row:
        raise ValueError("Missing checkpoint row")
    return ExtractionResult.model_validate(
        {
            "article_number": row["article_number"],
            "raw_entities": row.get("raw_entities", []),
            "entities": row.get("entities", []),
            "relations": row.get("relations", []),
            "resolved_model": row.get("resolved_model"),
        }
    )


def _load_checkpoints(path: Path, registry: StructuralRegistry, parsed: ParsedDocument) -> dict[str, dict]:
    if not path.exists():
        return {}
    articles = {article.number: article for article in parsed.articles}
    contexts = {number: registry.context_for_article(article) for number, article in articles.items()}
    valid: dict[str, dict] = {}
    seen_articles: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        article_number = str(row.get("article_number", ""))
        if article_number in seen_articles:
            raise ValueError(f"Duplicate Article checkpoint: {article_number}")
        seen_articles.add(article_number)
        context = contexts.get(article_number)
        if context and row.get("fingerprint") == _checkpoint_fingerprint(
            context, articles[article_number].content_raw
        ):
            valid[article_number] = row
    return valid


def _write_checkpoints(path: Path, checkpoints: dict[str, dict]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for article_number in sorted(checkpoints):
            handle.write(json.dumps(checkpoints[article_number], ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def _write_extraction_blocked(out_dir: Path, exc: Exception) -> None:
    for name in ("extract.jsonl", "accepted.jsonl", "review.jsonl", "rejected.jsonl"):
        (out_dir / name).write_text("", encoding="utf-8")
    (out_dir / "entity_index.json").write_text("{}", encoding="utf-8")
    blocked = {
        "blocked": True,
        "stage": "extraction",
        "reason": str(exc),
        "provider": settings.llm_provider,
        "model": _configured_llm_model(),
        "accepted_semantic_relation_count": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "extraction_blocked.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _apply_decision_gate(record: dict) -> dict:
    record = dict(record)
    if not record.get("schema_valid") or not record.get("ontology_valid"):
        record["decision"] = "rejected"
        record["review_reason"] = record.get("review_reason")
        record["blocking"] = bool(record.get("blocking"))
        return record

    if not record.get("consistency_valid"):
        record["decision"] = "review" if record.get("review_reason") else "rejected"
        record["blocking"] = bool(record.get("blocking", True))
        return record

    confidence = float(record.get("confidence") or 0.0)
    if confidence >= settings.confidence_threshold_auto:
        record["decision"] = "accepted"
        record["review_reason"] = None
        record["blocking"] = False
    elif confidence >= settings.confidence_threshold_review:
        record["decision"] = "review"
        record["review_reason"] = record.get("review_reason") or "low_confidence"
        record["blocking"] = False
    else:
        record["decision"] = "rejected"
        record["review_reason"] = record.get("review_reason") or "low_confidence"
        record["blocking"] = False
    return record


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
