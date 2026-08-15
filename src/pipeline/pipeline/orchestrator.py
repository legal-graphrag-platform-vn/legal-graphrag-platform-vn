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
from src.pipeline.extraction.diagram_parser import parse_diagram
from src.pipeline.extraction.document_relation_resolver import (
    build_diagram_records,
    resolve_diagram_relations,
)
from src.pipeline.extraction.llm_extractor import extract_article
from src.pipeline.extraction.models import ExtractedEntity
from src.pipeline.extraction.models import ExtractionResult
from src.pipeline.extraction.providers.base import ExtractionProviderError
from src.pipeline.extraction.provider_relation_candidates import (
    load_provider_relation_candidates,
    provider_owned_source_spans,
)
from src.pipeline.extraction.provider_relation_records import (
    PROVIDER_EXTRACTION_METHOD,
    build_provider_relation_records,
)
from src.pipeline.extraction.structural_context import (
    ENDPOINT_CONTRACT_VERSION,
    PROMPT_VERSION,
    ArticleExtractionContext,
    DocumentRegistry,
    EndpointResolution,
    StructuralRegistry,
)
from src.pipeline.extraction.structural_references import (
    LINKER_NAME,
    LINKER_VERSION,
    RESOLVER_NAME,
    RESOLVER_VERSION,
    ResolvedReference,
    StructuralReferenceResolver,
)
from src.pipeline.pipeline.artifact_store import (
    create_staging_artifact_dir,
    discard_staging_artifacts,
    publish_staged_artifacts,
)
from src.pipeline.pipeline.reference_checkpoint_store import (
    ReferenceCheckpointStore,
    ReferenceCheckpointV2,
    checkpoint_from_reference,
    committed_target_history,
)
from src.pipeline.parser.hierarchy_parser import canonicalize_source_text
from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument
from src.pipeline.scoring.confidence_scorer import score
from src.shared.ontology.validators import validate_relation as validate_ontology
from src.shared.ontology.contract import (
    DOCUMENT_RELATION_EXTRACTION_METHODS,
    ONTOLOGY_VERSION,
    SYNTHETIC_ARTICLE_NUMBER_PREFIX,
)
from src.pipeline.validation.record_consistency_validator import (
    validate_record_relation,
)
from src.pipeline.validation.schema_validator import (
    validate_relation as validate_schema,
)

logger = logging.getLogger(__name__)

NORMALIZER_VERSION = "structural-endpoint-v4"
RELATION_ENRICHER_VERSION = "checkpoint-provenance-v1"
DIAGRAM_RELATION_TYPES = frozenset({"AMENDS", "REPEALS", "REPLACES", "GUIDES"})
DIAGRAM_REVIEW_REASONS = frozenset(
    {"unresolved_diagram_target", "temporal_metadata_incomplete"}
)


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
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
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


def _normalize_checkpoint_timestamp(value: str | None) -> str:
    if not value:
        raise ValueError("Extraction checkpoint is missing completed_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid checkpoint completed_at: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("Extraction checkpoint completed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _checkpoint_llm_model(result: ExtractionResult) -> str:
    if not result.provider:
        raise ValueError("Extraction checkpoint is missing provider")
    if not result.resolved_model:
        raise ValueError("Extraction checkpoint is missing resolved_model")
    return f"{result.provider.lower()}:{result.resolved_model}"


def _relation_properties(
    raw_relation,
    article: Article,
    article_id: str,
    document: DocumentInfo,
    extraction_result: ExtractionResult,
) -> dict:
    relation_properties = {}

    if (
        raw_relation.relation in {"AMENDS", "REPEALS", "REPLACES"}
        and document.effective_from
    ):
        relation_properties["effective_from"] = str(document.effective_from)
    if raw_relation.relation == "AMENDS":
        relation_properties["source_doc_id"] = document.id
    if raw_relation.relation == "REFERS_TO":
        relation_properties["citation_text"] = raw_relation.evidence
        relation_properties["citation_type"] = "DIRECT"
        relation_properties["extraction_method"] = "LLM"
        relation_properties["reference_bundle_id"] = _llm_reference_bundle_id(
            article_id, raw_relation.head, raw_relation.tail, raw_relation.evidence
        )
        relation_properties["reference_target_count"] = 1
        relation_properties["checkpoint_id"] = (
            extraction_result.checkpoint_id
            or _derived_checkpoint_id(article_id, extraction_result)
        )
    if raw_relation.relation in {"DEFINES", "REGULATES", "REQUIRES", "REFERS_TO"}:
        relation_properties["confidence"] = raw_relation.confidence
        relation_properties["llm_model"] = _checkpoint_llm_model(extraction_result)
        relation_properties["created_at"] = _normalize_checkpoint_timestamp(
            extraction_result.completed_at
        )
    if raw_relation.relation == "REQUIRES":
        relation_properties["source_article"] = article_id

    return relation_properties


def _llm_reference_bundle_id(
    article_id: str, head: str, tail: str, evidence: str
) -> str:
    source = "|".join(["LLM", article_id, head, tail, _normalize_citation(evidence)])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _derived_checkpoint_id(article_id: str, result: ExtractionResult) -> str:
    required = (result.provider, result.resolved_model, result.completed_at)
    if any(not value for value in required):
        raise ValueError("Extraction result is missing checkpoint identity provenance")
    source = "|".join([article_id, *[str(value) for value in required]])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _normalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip())


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
    document_registry = document_registry or DocumentRegistry.from_manifest(
        settings.curated_manifest_path
    )
    result = extraction_result or extract_article(
        article.number, article_text, context=context
    )

    entity_types = _entity_type_lookup(result.entities)
    if entity_index is not None:
        for entity in result.entities:
            entry = _entity_index_entry(entity)
            if entry:
                existing = entity_index.get(entry["id"])
                if existing is not None and existing != entry:
                    raise ValueError(
                        f"Conflicting semantic entity normalization: {entry['id']}"
                    )
                entity_index[entry["id"]] = entry

    semantic_entries: dict[str, dict] = {}
    for entity in result.entities:
        entry = _entity_index_entry(entity)
        if entry:
            semantic_entries[entity.id] = entry
    known_ids = set(registry.types) | {
        entry["id"] for entry in semantic_entries.values()
    }

    for raw_relation in result.relations:
        raw_relation_dict = raw_relation.model_dump()
        head_resolution = _resolve_endpoint(
            raw_relation.head,
            entity_types,
            result.entities,
            semantic_entries,
            registry,
            document_registry,
            context.article_id,
        )
        tail_resolution = _resolve_endpoint(
            raw_relation.tail,
            entity_types,
            result.entities,
            semantic_entries,
            registry,
            document_registry,
            context.article_id,
        )
        relation_dict = raw_relation.model_dump()
        if head_resolution.canonical_id:
            relation_dict["head"] = head_resolution.canonical_id
        if tail_resolution.canonical_id:
            relation_dict["tail"] = tail_resolution.canonical_id
        parsed_relation, schema_err = validate_schema(relation_dict)
        schema_valid = parsed_relation is not None

        head_type = head_resolution.canonical_type or _ontology_label(
            entity_types.get(raw_relation.head, "Entity")
        )
        tail_type = tail_resolution.canonical_type or _ontology_label(
            entity_types.get(raw_relation.tail, "Entity")
        )
        head_doc_type = document.doc_type if head_type == "Document" else None
        tail_doc_type = document.doc_type if tail_type == "Document" else None

        # 1.   Construct actual relationship properties from document metadata and context
        relation_properties = _relation_properties(
            raw_relation, article, context.article_id, document, result
        )

        # 2.   Enrich the relation dictionary with actual properties
        relation_dict["properties"] = relation_properties

        if raw_relation.relation == "CONTAINS":
            ontology_ok, ontology_err = False, "llm_structural_relation_forbidden"
        elif (
            head_resolution.status == "rejected" or tail_resolution.status == "rejected"
        ):
            ontology_ok, ontology_err = (
                False,
                head_resolution.reason or tail_resolution.reason,
            )
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
            "article_id": context.article_id,
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
    if checkpoint:
        result = _result_from_checkpoint(checkpoint)
    else:
        extracted = extract_article(
            article.number, article.content_raw, context=context
        )
        checkpoint_id = _checkpoint_fingerprint(
            context,
            article.content_raw,
            provider=settings.llm_provider,
            configured_model=_configured_llm_model(),
        )
        result = extracted.model_copy(
            update={
                "provider": settings.llm_provider,
                "configured_model": _configured_llm_model(),
                "completed_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "checkpoint_id": checkpoint_id,
            }
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


def _validate_diagram_records(
    records: list[dict],
    *,
    current_document: DocumentInfo,
    registry: DocumentRegistry,
) -> list[dict]:
    """Validate deterministic document relations without trusting builder flags."""
    validated_records: list[dict] = []
    known_document_ids = set(registry.document_ids) | {current_document.id}

    for raw_record in records:
        record = dict(raw_record)
        relation = dict(record.get("relation") or {})
        properties = dict(relation.get("properties") or {})
        relation["properties"] = properties
        record["relation"] = relation

        parsed_relation, schema_error = validate_schema(relation)
        schema_valid = parsed_relation is not None
        record["schema_valid"] = schema_valid
        record["schema_error"] = schema_error
        if not schema_valid:
            record.update(
                ontology_valid=False,
                ontology_error="diagram_schema_invalid",
                consistency_valid=False,
                consistency_error="diagram_schema_invalid",
                review_reason=None,
                blocking=True,
            )
            validated_records.append(record)
            continue

        endpoint_resolution = record.get("endpoint_resolution") or {}
        if any(
            endpoint_resolution.get(endpoint, {}).get("status") != "resolved"
            for endpoint in ("head", "tail")
        ):
            record.update(
                schema_valid=True,
                ontology_valid=False,
                consistency_valid=False,
                review_reason="unresolved_diagram_target",
                blocking=True,
            )
            validated_records.append(record)
            continue

        relation_type = str(relation.get("relation") or "")
        extraction_method = properties.get("extraction_method")

        if (
            extraction_method not in DOCUMENT_RELATION_EXTRACTION_METHODS
            or relation_type not in DIAGRAM_RELATION_TYPES
        ):
            record.update(
                ontology_valid=False,
                ontology_error=(
                    "DIAGRAM only supports AMENDS, REPEALS, REPLACES, or GUIDES"
                ),
                consistency_valid=False,
                consistency_error="unsupported_diagram_relation",
                review_reason=None,
                blocking=True,
            )
            validated_records.append(record)
            continue

        head_id = str(relation.get("head") or "")
        tail_id = str(relation.get("tail") or "")
        head_doc_type = (
            current_document.doc_type
            if head_id == current_document.id
            else registry.document_type_for_id(head_id)
        )
        tail_doc_type = (
            current_document.doc_type
            if tail_id == current_document.id
            else registry.document_type_for_id(tail_id)
        )

        if relation_type in {"AMENDS", "REPEALS", "REPLACES"} and not properties.get(
            "effective_from"
        ):
            if head_id == current_document.id and current_document.effective_from:
                properties["effective_from"] = str(current_document.effective_from)
            else:
                ontology_ok, ontology_error = validate_ontology(
                    "Document",
                    relation_type,
                    "Document",
                    head_id=head_id,
                    tail_id=tail_id,
                    properties=properties,
                )
                record.update(
                    ontology_valid=ontology_ok,
                    ontology_error=ontology_error,
                    consistency_valid=False,
                    consistency_error=f"{relation_type} missing effective_from",
                    review_reason="temporal_metadata_incomplete",
                    blocking=True,
                )
                validated_records.append(record)
                continue

        ontology_ok, ontology_error = validate_ontology(
            "Document",
            relation_type,
            "Document",
            head_id=head_id,
            tail_id=tail_id,
            properties=properties,
            head_doc_type=head_doc_type,
            tail_doc_type=tail_doc_type,
        )
        consistency = validate_record_relation(
            relation_type=relation_type,
            head_id=head_id,
            tail_id=tail_id,
            properties=properties,
            known_entity_ids=known_document_ids,
            ontology_valid=ontology_ok,
            head_type="Document" if head_doc_type else None,
            tail_type="Document" if tail_doc_type else None,
        )
        record.update(
            ontology_valid=ontology_ok,
            ontology_error=ontology_error,
            consistency_valid=consistency.valid,
            consistency_error=consistency.error,
            review_reason=consistency.review_reason,
            blocking=consistency.blocking,
        )
        validated_records.append(record)

    return validated_records


# Kích thước tối đa mỗi chunk synthetic (ký tự) — ~750 token, vừa context window LLM
_SYNTHETIC_CHUNK_MAX_CHARS = 3000

# Regex nhận diện ranh giới Roman-outline phổ biến trong Thông tư cũ:
# I/ TÊN, II. TÊN, III - TÊN, I- TÊN (đầu dòng, chữ in hoa sau)
_ROMAN_OUTLINE_RE = re.compile(
    r"^([IVX]+)\s*[/\.\-]\s+([A-ZĐÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸ].+)$",
    re.UNICODE,
)


def _is_synthetic(article: Article) -> bool:
    """Kiểm tra xem Article có phải là synthetic (tạo từ SOURCE_PRESERVED) không."""
    return article.number.startswith(SYNTHETIC_ARTICLE_NUMBER_PREFIX)


def _split_by_roman_outline(text: str) -> list[tuple[str, str]]:
    """Split text theo Roman-outline headers, trả về list (heading, content).

    Ví dụ: 'I/ NHỮNG QUY ĐỊNH CHUNG\n...' -> [('I/ NHỮNG QUY ĐỊNH CHUNG', '...')]
    Trả về [] nếu không tìm thấy đủ ranh giới (< 2 chunks).
    """
    lines = text.splitlines()
    chunks: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if _ROMAN_OUTLINE_RE.match(line.strip()):
            # Flush chunk hiện tại
            if current_lines or current_heading is not None:
                chunks.append((current_heading or "", "\n".join(current_lines).strip()))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines or current_heading is not None:
        chunks.append((current_heading or "", "\n".join(current_lines).strip()))

    # Chỉ trả về kết quả nếu thực sự phân tách được
    return chunks if len(chunks) >= 2 else []


def _split_by_size(text: str, max_chars: int) -> list[tuple[str, str]]:
    """Fallback: chunk text theo kích thước, cắt tại ranh giới dòng gần nhất."""
    chunks: list[tuple[str, str]] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Cắt tại dòng mới gần nhất để tránh cắt giữa câu
            newline = text.rfind("\n", start, end)
            if newline > start:
                end = newline
        chunks.append(("", text[start:end].strip()))
        start = end
    return chunks


def _synthetic_articles_from_unparsed(parsed: ParsedDocument) -> list[Article]:
    """Tạo synthetic Articles từ unparsed_sections khi document SOURCE_PRESERVED.

    Chiến lược:
    1. Thử split text theo Roman-outline headers (I/, II., I- ...)
    2. Fallback: split theo kích thước (_SYNTHETIC_CHUNK_MAX_CHARS ký tự/chunk)

    Synthetic Articles có number='SP_1', 'SP_2', ... để phân biệt với Điều thật.
    Không có chapter/section/part — được gắn thẳng vào Document node trong graph.
    """
    body_sections = [
        s for s in parsed.unparsed_sections if s.section_type == "UNPARSED_BODY"
    ]
    if not body_sections:
        return []

    full_text = "\n".join(s.content_raw for s in body_sections).strip()
    if not full_text:
        return []

    # Thử split theo Roman outline trước
    chunks = _split_by_roman_outline(full_text)

    # Fallback: split theo kích thước
    if not chunks:
        chunks = _split_by_size(full_text, _SYNTHETIC_CHUNK_MAX_CHARS)

    if not chunks:
        return []

    articles: list[Article] = []
    for i, (heading, content) in enumerate(chunks, start=1):
        if not content:
            continue
        articles.append(
            Article(
                number=f"{SYNTHETIC_ARTICLE_NUMBER_PREFIX}{i}",
                title=heading or f"[Phần {i}]",
                content_raw=content,
                # source spans trỏ vào toàn bộ body section
                source_start_char=body_sections[0].source_start_char,
                source_end_char=body_sections[-1].source_end_char,
            )
        )
    return articles


def _validate_structural_reference_source(
    articles: list[Article],
    *,
    source_text: str | None,
    source_path: Path,
) -> None:
    structural_units = []
    for article in articles:
        structural_units.append((f"Article {article.number}", article))
        for clause in article.clauses:
            structural_units.append(
                (f"Clause {article.number}.{clause.number}", clause)
            )
            structural_units.extend(
                (
                    f"Point {article.number}.{clause.number}.{point.label}",
                    point,
                )
                for point in clause.points
            )
    has_source_spans = any(
        unit.source_end_char > unit.source_start_char for _, unit in structural_units
    )
    if source_text is None:
        if has_source_spans:
            raise ValueError(
                "Missing canonical source for structural reference resolution: "
                f"{source_path}"
            )
        return

    source_length = len(canonicalize_source_text(source_text))
    invalid_units = [
        label
        for label, unit in structural_units
        if not (0 <= unit.source_start_char < unit.source_end_char <= source_length)
    ]
    if invalid_units:
        raise ValueError(
            "Hierarchy has no usable canonical source span for structural unit(s): "
            f"{', '.join(invalid_units[:10])}. Rerun parse before extraction."
        )


def run_pipeline(
    parsed: ParsedDocument,
    processed_dir: Path,
    *,
    raw_doc_code: str,
    provider_calls_allowed: bool = True,
    article_numbers: set[str] | None = None,
    source_text: str | None = None,
    diagram: dict | None = None,
) -> None:
    if not raw_doc_code:
        raise ValueError("raw_doc_code is required for pipeline output path")

    out_dir = processed_dir / raw_doc_code
    out_dir.mkdir(parents=True, exist_ok=True)

    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    all_records = []
    entity_index: dict[str, dict] = {}
    semantic_type_conflicts: set[str] = set()
    registry = StructuralRegistry.from_parsed_document(parsed, raw_doc_code)
    available_articles = [
        *parsed.articles,
        *[article for appendix in parsed.appendices for article in appendix.articles],
        *[
            article
            for instrument in parsed.attached_instruments
            for article in instrument.articles
        ],
        *[
            article
            for instrument in parsed.attached_instruments
            for appendix in instrument.appendices
            for article in appendix.articles
        ],
    ]
    contexts_by_model = {
        id(article): registry.context_for_article(article)
        for article in available_articles
    }
    if article_numbers is None:
        selected_articles = available_articles
    else:
        selected_articles = []
        for selector in sorted(article_numbers):
            matches = [
                article
                for article in available_articles
                if article.number == selector
                or contexts_by_model[id(article)].article_id == selector
            ]
            if len(matches) > 1:
                raise ValueError(
                    f"Selected Article is ambiguous; use canonical article_id: {selector}"
                )
            if matches:
                selected_articles.append(matches[0])
    if article_numbers is not None:
        found = {
            selector
            for selector in article_numbers
            if any(
                article.number == selector
                or contexts_by_model[id(article)].article_id == selector
                for article in selected_articles
            )
        }
        missing_selection = sorted(article_numbers - found)
        if missing_selection:
            raise ValueError(
                f"Selected Article(s) not found in hierarchy: {missing_selection}"
            )
    # Khi document SOURCE_PRESERVED (0 Article từ parser), tạo synthetic Articles
    # từ unparsed_sections để extraction vẫn có thể chạy được trên toàn văn bản thô.
    if not available_articles:
        synthetic = _synthetic_articles_from_unparsed(parsed)
        if synthetic:
            logger.info(
                "Document %s có 0 Điều (SOURCE_PRESERVED); tạo %d synthetic chunk Article(s) "
                "từ unparsed_sections để extraction.",
                raw_doc_code,
                len(synthetic),
            )
            available_articles = synthetic
            # Tạo synthetic contexts: article_id = '{graph_id}_SP_{i}'
            for article in synthetic:
                contexts_by_model[id(article)] = ArticleExtractionContext(
                    raw_doc_code=raw_doc_code,
                    graph_id=parsed.document.id,
                    article_number=article.number,
                    article_id=f"{parsed.document.id}_{article.number}",
                    clause_ids={},
                    point_ids={},
                )
            # Cập nhật selected_articles
            if article_numbers is None:
                selected_articles = available_articles

    if not selected_articles:
        raise ValueError("Extraction requires at least one selected Article")

    source_path = settings.data_raw_dir / raw_doc_code / "source.txt"
    # Synthetic articles không có source spans chính xác theo Điều
    # → bỏ qua source span validation để tránh crash.
    if not any(_is_synthetic(a) for a in selected_articles):
        _validate_structural_reference_source(
            selected_articles,
            source_text=source_text,
            source_path=source_path,
        )
    document_registry = DocumentRegistry.from_manifest(settings.curated_manifest_path)
    provider_candidates = load_provider_relation_candidates(
        out_dir / "provider_relation_candidates.jsonl"
    )
    provider_relation_records = build_provider_relation_records(
        provider_candidates,
        document=parsed.document,
        registry=registry,
        source_text=source_text or "",
        selected_article_numbers={article.number for article in selected_articles},
    )
    checkpoint_path = out_dir / "article_extractions.jsonl"
    checkpoints = _load_checkpoints(
        checkpoint_path,
        registry,
        parsed,
        allow_legacy_prompt=not provider_calls_allowed,
    )
    provider_called = provider_calls_allowed and any(
        contexts_by_model[id(article)].article_id not in checkpoints
        for article in selected_articles
    )
    if not provider_calls_allowed:
        missing = [
            contexts_by_model[id(article)].article_id
            for article in selected_articles
            if contexts_by_model[id(article)].article_id not in checkpoints
        ]
        if missing:
            raise ValueError(
                f"Missing valid Article extraction checkpoints: {missing[:10]}"
            )
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
        article_id = contexts_by_model[id(article)].article_id
        checkpoint = checkpoints.get(article_id)
        future = executor.submit(
            _process_article_worker,
            article,
            parsed.document,
            registry,
            document_registry,
            checkpoint,
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
                    logger.error(
                        "Extraction blocked at Điều %s: %s", article.number, exc
                    )
                    if isinstance(exc, ExtractionProviderError):
                        raise
                    raise RuntimeError(
                        f"Extraction failed at Article {article.number}: {exc}"
                    ) from exc

                completed += 1
                article_id = contexts_by_model[id(article)].article_id
                results_by_article[article_id] = records
                for entity_id, entry in article_entity_index.items():
                    existing = entity_index.get(entity_id)
                    if existing is not None and existing.get("type") != entry.get(
                        "type"
                    ):
                        semantic_type_conflicts.add(entity_id)
                    elif entity_id not in semantic_type_conflicts:
                        entity_index[entity_id] = entry
                existing_models = {
                    row.get("resolved_model")
                    for row in checkpoints.values()
                    if row.get("resolved_model")
                }
                if (
                    checkpoint_row.get("resolved_model")
                    and existing_models
                    and checkpoint_row["resolved_model"] not in existing_models
                ):
                    error = RuntimeError(
                        "Resolved model changed within extraction checkpoints: "
                        f"existing={sorted(existing_models)}, new={checkpoint_row['resolved_model']}"
                    )
                    _write_extraction_blocked(out_dir, error)
                    raise error
                checkpoints[article_id] = checkpoint_row
                _write_checkpoints(checkpoint_path, checkpoints)
                logger.info(
                    "Đã trích xuất xong Điều %s (%d/%d)",
                    article.number,
                    completed,
                    total,
                )
                submit_next()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    # Đảm bảo giữ đúng thứ tự các Điều trong văn bản gốc
    for article in selected_articles:
        article_id = contexts_by_model[id(article)].article_id
        if article_id in results_by_article:
            all_records.extend(results_by_article[article_id])

    reference_resolver = StructuralReferenceResolver(
        registry,
        source_text or "",
        excluded_source_spans=provider_owned_source_spans(
            provider_candidates, source_text or ""
        ),
    )
    resolved_references = (
        [
            reference
            for article in selected_articles
            for reference in reference_resolver.resolve_article(article)
        ]
        if source_text
        else []
    )
    reference_checkpoint_path = out_dir / "reference_resolutions.jsonl"
    reference_checkpoints = _update_reference_checkpoints(
        reference_checkpoint_path,
        resolved_references,
        selected_article_ids={
            contexts_by_model[id(article)].article_id for article in selected_articles
        },
    )
    rule_records = _rule_reference_records(
        resolved_references, reference_checkpoints, registry
    )
    all_records.extend(rule_records)
    _mark_llm_relations_superseded_by_rules(all_records)

    all_records.extend(provider_relation_records)

    # Diagram relations — document-level, deterministic, chạy sau rule records.
    if diagram:
        document_registry = DocumentRegistry.from_manifest(
            settings.curated_manifest_path
        )
        diagram_result = parse_diagram(diagram)
        for unknown_cat in diagram_result.unknown_categories:
            logger.warning(
                "Diagram: unknown category %r — không có trong DOCUMENT_RELATION_MAP "
                "và không phải UNSUPPORTED. Kiểm tra vbpl.vn có thêm category mới không.",
                unknown_cat,
            )
        diagram_resolved, diagram_unresolved = resolve_diagram_relations(
            diagram_result.candidates,
            current_document_id=parsed.document.id,
            registry=document_registry,
        )
        diagram_records = build_diagram_records(
            diagram_resolved,
            diagram_unresolved,
            current_document_id=parsed.document.id,
        )
        diagram_records = _validate_diagram_records(
            diagram_records,
            current_document=parsed.document,
            registry=document_registry,
        )
        logger.info(
            "Diagram extraction: %d resolved, %d unresolved, %d unknown categories",
            len(diagram_resolved),
            len(diagram_unresolved),
            len(diagram_result.unknown_categories),
        )
        all_records.extend(diagram_records)

    for entity_id in semantic_type_conflicts:
        entity_index.pop(entity_id, None)
    for record in all_records:
        relation = record.get("relation") or {}
        conflicted = sorted(
            endpoint
            for endpoint in (relation.get("head"), relation.get("tail"))
            if endpoint in semantic_type_conflicts
        )
        if conflicted and record.get("schema_valid") and record.get("ontology_valid"):
            record["consistency_valid"] = False
            record["consistency_error"] = (
                f"Conflicting semantic type for endpoint(s): {conflicted}"
            )
            record["review_reason"] = "semantic_type_conflict"
            record["blocking"] = False

    all_records = _apply_atomic_bundle_decisions(
        [_apply_decision_gate(record) for record in all_records]
    )

    artifact_set_id, staging = create_staging_artifact_dir(out_dir)
    try:
        _write_jsonl(staging / "extract.jsonl", all_records)
        (staging / "prettier_extract.json").write_text(
            json.dumps(all_records, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        _write_jsonl(
            staging / "accepted.jsonl",
            [r for r in all_records if r["decision"] == "accepted"],
        )
        _write_jsonl(
            staging / "review.jsonl",
            [r for r in all_records if r["decision"] == "review"],
        )
        _write_jsonl(
            staging / "rejected.jsonl",
            [r for r in all_records if r["decision"] == "rejected"],
        )
        (staging / "entity_index.json").write_text(
            json.dumps(entity_index, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (staging / "extraction_run.json").write_text(
            json.dumps(
                {
                    "artifact_set_id": artifact_set_id,
                    "raw_doc_code": raw_doc_code,
                    "graph_id": parsed.document.id,
                    "ontology_version": ONTOLOGY_VERSION,
                    "adr": "ADR-22",
                    "normalizer_version": NORMALIZER_VERSION,
                    "relation_enricher_version": RELATION_ENRICHER_VERSION,
                    "source": "article_extractions.jsonl checkpoints",
                    "provider_called": provider_called,
                    "selected_articles": [
                        article.number for article in selected_articles
                    ],
                    "document_article_count": len(parsed.articles),
                    "complete_document": len(selected_articles)
                    == len(available_articles),
                    "prompt_version": PROMPT_VERSION,
                    "source_prompt_versions": sorted(
                        {
                            str(row.get("prompt_version") or "legacy-unspecified")
                            for row in checkpoints.values()
                        }
                    ),
                    "endpoint_contract_version": ENDPOINT_CONTRACT_VERSION,
                    "resolver_name": RESOLVER_NAME,
                    "resolver_version": RESOLVER_VERSION,
                    "semantic_type_conflict_count": len(semantic_type_conflicts),
                    "semantic_type_conflicts": sorted(semantic_type_conflicts),
                    "structural_reference_count": len(resolved_references),
                    "rule_relation_count": len(rule_records),
                    "provider_candidate_count": len(provider_candidates),
                    "provider_relation_record_count": len(provider_relation_records),
                    "completed_at": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        publish_staged_artifacts(out_dir, artifact_set_id, staging)
    except Exception:
        discard_staging_artifacts(staging)
        raise
    (out_dir / "extraction_blocked.json").unlink(missing_ok=True)


def _checkpoint_fingerprint(
    context,
    article_text: str,
    *,
    provider: str | None = None,
    configured_model: str | None = None,
) -> str:
    source = "|".join(
        [
            context.to_prompt_json(),
            article_text,
            provider or settings.llm_provider,
            configured_model or _configured_llm_model(),
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
        "article_id": context.article_id,
        "fingerprint": _checkpoint_fingerprint(
            context,
            article_text,
            provider=result.provider,
            configured_model=result.configured_model,
        ),
        "provider": result.provider,
        "configured_model": result.configured_model,
        "resolved_model": result.resolved_model,
        "prompt_version": PROMPT_VERSION,
        "endpoint_contract_version": ENDPOINT_CONTRACT_VERSION,
        "content_hash": hashlib.sha256(article_text.encode("utf-8")).hexdigest(),
        "raw_entities": [entity.model_dump() for entity in result.raw_entities],
        "entities": [entity.model_dump() for entity in result.entities],
        "relations": [relation.model_dump() for relation in result.relations],
        "completed_at": _normalize_checkpoint_timestamp(result.completed_at),
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
            "provider": row.get("provider"),
            "configured_model": row.get("configured_model"),
            "resolved_model": row.get("resolved_model"),
            "completed_at": _normalize_checkpoint_timestamp(row.get("completed_at")),
            "checkpoint_id": row.get("fingerprint"),
        }
    )


def _load_checkpoints(
    path: Path,
    registry: StructuralRegistry,
    parsed: ParsedDocument,
    *,
    allow_legacy_prompt: bool = False,
) -> dict[str, dict]:
    if not path.exists():
        return {}
    all_articles = [
        *parsed.articles,
        *[article for appendix in parsed.appendices for article in appendix.articles],
        *[
            article
            for instrument in parsed.attached_instruments
            for article in instrument.articles
        ],
        *[
            article
            for instrument in parsed.attached_instruments
            for appendix in instrument.appendices
            for article in appendix.articles
        ],
    ]
    contexts = {
        registry.context_for_article(article).article_id: registry.context_for_article(
            article
        )
        for article in all_articles
    }
    articles = {
        registry.context_for_article(article).article_id: article
        for article in all_articles
    }
    valid: dict[str, dict] = {}
    seen_articles: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        article_id = str(row.get("article_id", ""))
        if not article_id:
            matching_ids = [
                candidate_id
                for candidate_id, article in articles.items()
                if article.number == str(row.get("article_number", ""))
            ]
            article_id = matching_ids[0] if len(matching_ids) == 1 else ""
        if article_id in seen_articles:
            raise ValueError(f"Duplicate Article checkpoint: {article_id}")
        seen_articles.add(article_id)
        context = contexts.get(article_id)
        if context is None:
            continue
        current_content_hash = hashlib.sha256(
            articles[article_id].content_raw.encode("utf-8")
        ).hexdigest()
        current_fingerprint = (
            _checkpoint_fingerprint(
                context,
                articles[article_id].content_raw,
                provider=row.get("provider"),
                configured_model=row.get("configured_model"),
            )
            if context
            else None
        )
        exact_match = (
            context is not None and row.get("fingerprint") == current_fingerprint
        )
        legacy_match = (
            allow_legacy_prompt
            and context is not None
            and row.get("content_hash") == current_content_hash
            and row.get("provider")
            and row.get("resolved_model")
            and row.get("completed_at")
        )
        if exact_match or legacy_match:
            valid[article_id] = row
    return valid


def _write_checkpoints(path: Path, checkpoints: dict[str, dict]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for article_number in sorted(checkpoints):
            handle.write(
                json.dumps(checkpoints[article_number], ensure_ascii=False, default=str)
                + "\n"
            )
    temporary.replace(path)


def _write_extraction_blocked(out_dir: Path, exc: Exception) -> None:
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


def _update_reference_checkpoints(
    path: Path,
    references: list[ResolvedReference],
    *,
    selected_article_ids: set[str],
) -> dict[str, ReferenceCheckpointV2]:
    store = ReferenceCheckpointStore(path.parent)
    store.checkpoint_path = path
    with store.locked():
        existing = store.read_checkpoints()
        attempts = store.read_attempts()
        expected_hash = store.checkpoint_hash()
        updated: dict[str, ReferenceCheckpointV2] = {
            bundle_id: checkpoint
            for bundle_id, checkpoint in existing.items()
            if checkpoint.reference.mention.source_context.article_id
            not in selected_article_ids
            or checkpoint.materialization.status in {"WRITTEN", "BLOCKED"}
        }
        now = datetime.now(timezone.utc)
        for reference in references:
            bundle_id = reference.mention.reference_bundle_id
            prior = existing.get(bundle_id)
            if (
                prior is not None
                and prior.resolution.build_id is not None
                and reference.reference_scope == "EXTERNAL"
                and reference.status == "UNRESOLVED"
                and reference.reason_code == "target_document_not_in_snapshot"
            ):
                # Normal extraction has no corpus snapshot. Do not downgrade a
                # later reconciliation result merely because this stage cannot
                # reproduce its existence evidence.
                updated[bundle_id] = prior
                continue
            prior_written = bool(committed_target_history(attempts, bundle_id))
            updated[bundle_id] = checkpoint_from_reference(
                reference,
                resolver_name=RESOLVER_NAME,
                resolver_version=RESOLVER_VERSION,
                detected_at=now,
                prior=prior,
                prior_written=prior_written,
            )
        store.compare_and_swap(updated, expected_hash=expected_hash)
    return updated


def _rule_reference_records(
    references: list[ResolvedReference],
    checkpoints: dict[str, ReferenceCheckpointV2],
    registry: StructuralRegistry,
) -> list[dict]:
    records: list[dict] = []
    known_ids = set(registry.types)
    for reference in references:
        if (
            reference.status != "RESOLVED"
            or reference.reference_scope != "LOCAL"
            or reference.is_self_reference
        ):
            continue
        mention = reference.mention
        source_id = mention.source_context.source_unit_id
        checkpoint = checkpoints[mention.reference_bundle_id]
        citation_type = "RANGE" if len(reference.target_unit_ids) > 1 else "DIRECT"
        for target_id in reference.target_unit_ids:
            extraction_method = (
                "ENTITY_LINKING"
                if reference.resolution_method == "ENTITY_LINKING"
                else "RULE"
            )
            properties = {
                "citation_text": mention.raw_text,
                "citation_type": citation_type,
                "extraction_method": extraction_method,
                "created_at": checkpoint.detected_at.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "reference_bundle_id": mention.reference_bundle_id,
                "reference_target_count": len(reference.target_unit_ids),
                "source_unit_id": source_id,
                "source_char_start": mention.source_char_start,
                "source_char_end": mention.source_char_end,
            }
            if extraction_method == "RULE":
                properties.update(
                    resolver_name=RESOLVER_NAME,
                    resolver_version=RESOLVER_VERSION,
                )
            else:
                properties.update(
                    linker_name=LINKER_NAME,
                    linker_version=LINKER_VERSION,
                )
            source_type = registry.types.get(source_id)
            target_type = registry.types.get(target_id) or _structural_type_from_id(
                target_id
            )
            ontology_ok, ontology_error = validate_ontology(
                source_type or "",
                "REFERS_TO",
                target_type or "",
                head_id=source_id,
                tail_id=target_id,
                properties=properties,
            )
            consistency = validate_record_relation(
                relation_type="REFERS_TO",
                head_id=source_id,
                tail_id=target_id,
                properties=properties,
                known_entity_ids=known_ids,
                ontology_valid=ontology_ok,
                head_type=source_type,
                tail_type=target_type,
            )
            relation = {
                "head": source_id,
                "relation": "REFERS_TO",
                "tail": target_id,
                "evidence": mention.raw_text,
                "properties": properties,
            }
            records.append(
                {
                    "document_id": mention.source_context.document_id,
                    "article_number": registry.article_number_for_id(
                        mention.source_context.article_id
                    ),
                    "raw_relation": relation,
                    "relation": relation,
                    "endpoint_resolution": {
                        "head": {
                            "status": "resolved",
                            "method": "rule",
                            "canonical_id": source_id,
                        },
                        "tail": {
                            "status": "resolved",
                            "method": "rule",
                            "canonical_id": target_id,
                        },
                    },
                    "schema_valid": True,
                    "schema_error": None,
                    "ontology_valid": ontology_ok,
                    "ontology_error": ontology_error,
                    "consistency_valid": consistency.valid,
                    "consistency_error": consistency.error,
                    "review_reason": consistency.review_reason,
                    "blocking": consistency.blocking,
                    "confidence": None,
                }
            )
    return records


def _structural_type_from_id(node_id: str) -> str | None:
    if re.search(r"_cl[^_]+_p[^_]+$", node_id):
        return "Point"
    if re.search(r"_art[^_]+_cl[^_]+$", node_id):
        return "Clause"
    if re.search(r"_art[^_]+$", node_id):
        return "Article"
    if re.search(r"_ch[^_]+_sec[^_]+_subsec[^_]+$", node_id):
        return "Subsection"
    if re.search(r"_ch[^_]+_sec[^_]+$", node_id):
        return "Section"
    if re.search(r"_ch[^_]+$", node_id):
        return "Chapter"
    if re.search(r"_part[^_]+$", node_id):
        return "Part"
    if re.search(r"_app[^_]+$", node_id):
        return "Appendix"
    if re.search(r"_inst[^_]+$", node_id):
        return "AttachedInstrument"
    return "Document" if node_id else None


def _mark_llm_relations_superseded_by_rules(records: list[dict]) -> None:
    deterministic_records = [
        record
        for record in records
        if (record.get("relation") or {}).get("relation") == "REFERS_TO"
        and (record.get("relation") or {})
        .get("properties", {})
        .get("extraction_method")
        in {"RULE", "ENTITY_LINKING"}
    ]
    for record in records:
        relation = record.get("relation") or {}
        properties = relation.get("properties") or {}
        if (
            properties.get("extraction_method") != "LLM"
            or relation.get("relation") != "REFERS_TO"
        ):
            continue
        evidence = _normalize_citation(str(properties.get("citation_text") or ""))
        for deterministic_record in deterministic_records:
            deterministic_relation = deterministic_record["relation"]
            deterministic_properties = deterministic_relation["properties"]
            deterministic_evidence = _normalize_citation(
                deterministic_properties["citation_text"]
            )
            same_source = relation.get("head") == deterministic_relation.get("head")
            same_citation = bool(
                deterministic_evidence
                and evidence
                and (
                    deterministic_evidence == evidence
                    or deterministic_evidence in evidence
                    or evidence in deterministic_evidence
                )
            )
            if same_source and same_citation:
                record["superseded_by_deterministic_resolution"] = (
                    deterministic_properties["reference_bundle_id"]
                )
                break


def _apply_decision_gate(record: dict) -> dict:
    record = dict(record)
    if record.get("superseded_by_deterministic_resolution"):
        record["decision"] = "rejected"
        record["review_reason"] = "superseded_by_deterministic_resolution"
        record["blocking"] = False
        return record
    if not record.get("schema_valid"):
        record["decision"] = "rejected"
        record["review_reason"] = record.get("review_reason")
        record["blocking"] = bool(record.get("blocking"))
        return record
    if (
        record.get("extraction_method") == "DIAGRAM"
        and record.get("review_reason") in DIAGRAM_REVIEW_REASONS
    ):
        record["decision"] = "review"
        record["blocking"] = True
        return record
    if not record.get("ontology_valid"):
        record["decision"] = "rejected"
        record["review_reason"] = record.get("review_reason")
        record["blocking"] = bool(record.get("blocking"))
        return record

    if not record.get("consistency_valid"):
        record["decision"] = "review" if record.get("review_reason") else "rejected"
        record["blocking"] = bool(record.get("blocking", True))
        return record

    extraction_method = (
        (record.get("relation") or {}).get("properties", {}).get("extraction_method")
    )
    if extraction_method in {
        "RULE",
        "ENTITY_LINKING",
        "DIAGRAM",
        PROVIDER_EXTRACTION_METHOD,
    }:
        record["decision"] = "accepted"
        record["review_reason"] = None
        record["blocking"] = False
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


def _apply_atomic_bundle_decisions(records: list[dict]) -> list[dict]:
    bundles: dict[str, list[dict]] = {}
    for record in records:
        properties = (record.get("relation") or {}).get("properties") or {}
        extraction_method = properties.get("extraction_method")
        if extraction_method not in {
            "RULE",
            "ENTITY_LINKING",
            PROVIDER_EXTRACTION_METHOD,
        }:
            continue
        bundle_id = (
            record.get("provider_bundle_id")
            if extraction_method == PROVIDER_EXTRACTION_METHOD
            else properties.get("reference_bundle_id")
        )
        if bundle_id:
            bundles.setdefault(str(bundle_id), []).append(record)

    for bundle_records in bundles.values():
        if all(record.get("decision") == "accepted" for record in bundle_records):
            continue
        bundle_decision = (
            "rejected"
            if any(record.get("decision") == "rejected" for record in bundle_records)
            else "review"
        )
        for record in bundle_records:
            record["decision"] = bundle_decision
            record["review_reason"] = "atomic_reference_bundle_validation_failed"
            record["blocking"] = True
    return records


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
