"""CLI entrypoint cho Graph Construction Pipeline (Milestone 1+2).

    python -m src.pipeline.main crawl --url <vbpl_url> --raw-doc-code L59_2020 --number 59/2020/QH14
    python -m src.pipeline.main parse --raw-doc-code L59_2020
    python -m src.pipeline.main extract --raw-doc-code L59_2020
    python -m src.pipeline.main ingest --url <vbpl_url> --raw-doc-code L59_2020 --number 59/2020/QH14

`extract` cần GEMINI_API_KEY trong .env (xem .env.example và README).
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated

import typer

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.pipeline.config import settings
from src.pipeline.crawler.vbpl_crawler import crawl_and_save, crawl_by_search
from src.pipeline.extraction.providers.base import ExtractionProviderError
from src.pipeline.extraction.provider_references import (
    ProviderReferenceMentionV1,
    ensure_luatvietnam_reference_sidecar,
)
from src.pipeline.extraction.provider_identity_index import (
    build_luatvietnam_identity_indexes,
)
from src.pipeline.extraction.provider_relation_candidates import (
    build_provider_relation_candidates,
    write_provider_relation_candidates,
)
from src.pipeline.extraction.corpus_structural_registry import (
    RegistryError,
    build_corpus_registry,
    load_registry_build,
    publish_registry_build,
)
from src.infrastructure.embedding.embedding_generator import (
    EmbeddingGenerator,
    embedding_content_hash,
    embedding_texts_by_node_id,
)
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter
from src.infrastructure.neo4j.graph_snapshot import generate_snapshot, write_snapshot
from src.infrastructure.neo4j.hierarchy_reconciler import SectionHierarchyReconciler
from src.infrastructure.neo4j.m3_runtime import (
    M3RuntimeGuardError,
    validate_disposable_uri,
)
from src.infrastructure.neo4j.schema_verifier import (
    SchemaVerificationError,
    verify_canonical_schema,
)
from src.infrastructure.neo4j.vector_smoke import (
    SMOKE_QUERIES,
    run_vector_smoke,
    write_vector_smoke_evidence,
)
from src.pipeline.parser.hierarchy_parser import parse_text_with_diagnostics
from src.pipeline.parser.models import DocumentInfo, ParsedDocument
from src.infrastructure.neo4j.writer import (
    GraphIngestionService,
    Neo4jWriter,
    create_neo4j_session,
    validate_graph_payload,
)
from src.pipeline.persistence.payload_builder import (
    PayloadBuildError,
    build_payload_from_paths,
)
from src.pipeline.persistence.validated_payload_loader import (
    ValidatedPayloadLoadError,
    load_validated_payload,
)
from src.pipeline.pipeline.external_reference_reconciliation import (
    reconcile_external_references as reconcile_external_reference_service,
    reference_status as load_reference_status,
)
from src.pipeline.pipeline.orchestrator import run_pipeline
from src.pipeline.reports.graph_quality import (
    GraphQualityReporter,
    decision_stats_from_paths,
    write_graph_quality_report,
)
from src.pipeline.reports.milestone_a import (
    MilestoneAReportError,
    generate_milestone_a_report,
    write_milestone_a_report,
)
from src.pipeline.validation.data_readiness import (
    load_curated_manifest,
    validate_document_readiness,
)
from src.pipeline.validation.manifest_builder import generate_manifest_file
from src.pipeline.pipeline.batch_progress_ledger import (
    filter_documents_for_step,
    record_doc_status,
)
from src.pipeline.validation.extraction_readiness import (
    ExtractionReadinessError,
    StructuralReadinessError,
    validate_extraction_readiness,
    validate_structural_readiness,
)
from src.shared.ontology.payload_consistency_validator import (
    validate_payload_consistency,
)
from src.shared.ontology.validators import GraphValidationError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="Legal GraphRAG — Graph Construction Pipeline (Milestone 1+2)")


def _document_info_from_metadata(meta: dict) -> DocumentInfo:
    return DocumentInfo(
        id=meta["graph_id"],
        title=meta["title"],
        number=meta["number"],
        doc_type=meta.get("doc_type") or meta.get("type"),
        issued_by=meta.get("issued_by"),
        issuer_name=meta.get("issuer_name") or meta.get("issued_by"),
        issued_date=meta.get("issued_date"),
        effective_from=meta.get("effective_from"),
        effective_to=meta.get("effective_to"),
        legal_status=meta["legal_status"],
        source_url=meta.get("source_url"),
        sector=meta.get("sector"),
        field=meta.get("field"),
        signer_title=meta.get("signer_title"),
        signer_name=meta.get("signer_name"),
    )


def _ready_metadata(
    raw_doc_code: str,
    raw_root: Path | None = None,
    manifest_path: Path | None = None,
) -> dict:
    readiness = validate_document_readiness(
        raw_doc_code,
        raw_root or settings.data_raw_dir,
        manifest_path=manifest_path or settings.curated_manifest_path,
    )
    if not readiness.valid:
        raise ValueError("; ".join(readiness.errors))
    return readiness.normalized_metadata


# Lấy đường dẫn thư mục lưu trữ dữ liệu thô (raw data) của văn bản.
def _raw_dir(raw_doc_code: str) -> Path:
    return settings.data_raw_dir / raw_doc_code


# Lấy đường dẫn thư mục lưu trữ dữ liệu đã xử lý (processed data) của văn bản.
def _processed_dir(raw_doc_code: str) -> Path:
    return settings.data_processed_dir / raw_doc_code


def _read_canonical_source(raw_doc_code: str) -> str:
    source_path = _raw_dir(raw_doc_code) / "source.txt"
    if not source_path.is_file():
        raise ValueError(f"Missing canonical source: {source_path}")
    return source_path.read_text(encoding="utf-8")


def _read_diagram(
    raw_doc_code: str, raw_root: Path | None = None
) -> dict[str, list[str]] | None:
    """Đọc diagram.json từ thư mục raw nếu tồn tại để trích xuất quan hệ liên văn bản."""
    base_raw_dir = raw_root or settings.data_raw_dir
    raw_doc_dir = (
        base_raw_dir / raw_doc_code
        if (base_raw_dir / raw_doc_code).exists()
        else settings.luatvietnam_raw_dir / raw_doc_code
    )
    diagram_path = raw_doc_dir / "diagram.json"
    if diagram_path.is_file():
        try:
            data = json.loads(diagram_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                groups = data.get("groups")
                if isinstance(groups, list):
                    result: dict[str, list[str]] = {}
                    for group in groups:
                        if isinstance(group, dict):
                            label = str(group.get("label") or "").strip()
                            items = group.get("items") or []
                            extracted_items: list[str] = []
                            for item in items:
                                if isinstance(item, dict):
                                    title = (
                                        item.get("title")
                                        or item.get("text")
                                        or item.get("number")
                                    )
                                    if title:
                                        extracted_items.append(str(title).strip())
                                elif isinstance(item, str) and item.strip():
                                    extracted_items.append(item.strip())
                            if label and extracted_items:
                                result[label] = extracted_items
                    return result
                return data
        except Exception as exc:
            logger.warning("Không thể đọc diagram.json cho %s: %s", raw_doc_code, exc)
    return None


def _write_parse_artifacts(
    out_dir: Path,
    parsed: ParsedDocument,
    source_text: str,
    provider_references: tuple[ProviderReferenceMentionV1, ...] = (),
    raw_root: Path | None = None,
) -> None:
    """Persist hierarchy with parser metadata and provider relation candidates."""

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hierarchy.json").write_text(
        parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
    )
    _write_provider_candidate_artifact(
        out_dir,
        parsed,
        source_text,
        provider_references,
        raw_root=raw_root,
    )


def _write_provider_candidate_artifact(
    out_dir: Path,
    parsed: ParsedDocument,
    source_text: str,
    provider_references: tuple[ProviderReferenceMentionV1, ...],
    *,
    raw_root: Path | None = None,
) -> None:
    document_index, document_number_index, unit_index, failure_index = (
        build_luatvietnam_identity_indexes(
            raw_root or settings.data_raw_dir,
            settings.data_processed_dir,
            parsed,
            provider_references,
        )
    )
    candidates = build_provider_relation_candidates(
        parsed,
        source_text,
        provider_references,
        provider_document_index=document_index,
        provider_document_number_index=document_number_index,
        provider_unit_index=unit_index,
        provider_failure_index=failure_index,
    )
    write_provider_relation_candidates(
        out_dir / "provider_relation_candidates.jsonl", candidates
    )


def _rebuild_provider_candidates_after_batch_parse(
    doc_codes: list[str], *, raw_root: Path
) -> None:
    """Rebuild provider identities after all available hierarchies are durable."""

    for raw_doc_code in doc_codes:
        raw_dir = raw_root / raw_doc_code
        hierarchy_path = settings.data_processed_dir / raw_doc_code / "hierarchy.json"
        source_path = raw_dir / "source.txt"
        if not hierarchy_path.is_file() or not source_path.is_file():
            continue
        parsed = ParsedDocument.model_validate_json(
            hierarchy_path.read_text(encoding="utf-8")
        )
        source_text = source_path.read_text(encoding="utf-8")
        references = ensure_luatvietnam_reference_sidecar(raw_dir)
        _write_provider_candidate_artifact(
            hierarchy_path.parent,
            parsed,
            source_text,
            references,
            raw_root=raw_root,
        )


def _parse_folder_worker(
    raw_doc_code: str,
    raw_root: Path | None = None,
    manifest_path: Path | None = None,
) -> bool:
    """Worker xử lý parse cho 1 thư mục đơn lẻ."""
    try:
        base_raw_dir = raw_root or settings.data_raw_dir
        raw_dir = base_raw_dir / raw_doc_code
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(
                f"Thư mục {raw_doc_code} thiếu source.txt hoặc metadata.json", err=True
            )
            return False

        doc_info = _document_info_from_metadata(
            _ready_metadata(
                raw_doc_code, raw_root=base_raw_dir, manifest_path=manifest_path
            )
        )

        provider_references = ensure_luatvietnam_reference_sidecar(raw_dir)
        text = source_path.read_text(encoding="utf-8")
        try:
            parsed, diagnostics = parse_text_with_diagnostics(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error [{raw_doc_code}]: {exc}", err=True)
            return False

        out_dir = settings.data_processed_dir / raw_doc_code
        _write_parse_artifacts(
            out_dir,
            parsed,
            text,
            provider_references,
            raw_root=base_raw_dir,
        )
        typer.echo(f"Parsed thành công {raw_doc_code} -> {out_dir / 'hierarchy.json'}")
        return True
    except Exception as e:
        typer.echo(f"Lỗi khi parse thư mục {raw_doc_code}: {e}", err=True)
        return False


# Lệnh CLI để cào thông tin chi tiết và nội dung văn bản pháp luật từ LuatVietnam hoặc VBPL.
@app.command()
def crawl(
    url: Annotated[
        str, typer.Option(help="URL trang chi tiết (luatvietnam.vn hoặc vbpl.vn)")
    ],
    raw_doc_code: Annotated[
        str | None,
        typer.Option(
            help="Filesystem document code, vd 'L59_2020'. Tùy chọn (tự sinh nếu để trống)"
        ),
    ] = None,
    number: Annotated[
        str | None, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'. Tùy chọn")
    ] = None,
) -> Path:
    """Crawl văn bản từ LuatVietnam (kèm bổ sung VBPL nếu có) hoặc từ VBPL -> data/raw/<raw_doc_code>/."""
    if "luatvietnam.vn" in url.lower():
        from src.pipeline.crawler.luatvietnam_crawler import crawl_luatvietnam_url

        saved_dir = crawl_luatvietnam_url(
            url,
            raw_doc_code=raw_doc_code,
            number=number,
            output_raw_dir=settings.data_raw_dir,
        )
        typer.echo(
            f"Đã crawl thành công LuatVietnam (bổ sung VBPL nếu có) tại: {saved_dir}"
        )
        return saved_dir
    else:
        doc_code = raw_doc_code or f"DOC_{int(datetime.now().timestamp())}"
        doc_number = number or ""
        metadata = crawl_and_save(
            url, doc_id=doc_code, number=doc_number, raw_dir=settings.data_raw_dir
        )
        typer.echo(f"Đã crawl {doc_code}: {metadata.title} ({metadata.status})")
        return settings.data_raw_dir / doc_code


# Lệnh CLI để cào hàng loạt văn bản pháp luật dựa trên từ khóa tìm kiếm trên vbpl.vn.
@app.command()
def crawl_search(
    query: Annotated[
        str,
        typer.Option(help="Từ khóa tìm kiếm trên vbpl.vn (vd: 'Luật Doanh nghiệp số')"),
    ],
    limit: Annotated[int, typer.Option(help="Số lượng văn bản tối đa muốn crawl")] = 10,
) -> None:
    """Crawl hàng loạt văn bản từ vbpl.vn dựa trên từ khóa tìm kiếm."""
    results = crawl_by_search(query, raw_dir=settings.data_raw_dir, limit=limit)
    typer.echo(
        f"Đã crawl thành công {len(results)} văn bản dựa trên tìm kiếm từ khóa '{query}'."
    )


# Lệnh CLI để phân tách cấu trúc văn bản pháp luật (Chương/Điều/Khoản/Điểm) từ file thô hoặc Text.
@app.command()
def parse(
    raw_doc_code: Annotated[
        str | None,
        typer.Option(
            help="Filesystem document code, vd 'L59_2020'. Nếu không truyền, parse mọi raw folder hợp lệ"
        ),
    ] = None,
    txt: Annotated[
        Path | None,
        typer.Option(help="Parse trực tiếp từ file text (.txt) tự chọn."),
    ] = None,
) -> None:
    """Parse văn bản -> data/processed/<raw_doc_code>/hierarchy.json.

    Mặc định đọc data/raw/<raw_doc_code>/source.txt (output của `crawl`, lấy từ HTML body).
    Dùng `--txt <path>` để parse trực tiếp từ file text (.txt).
    Nếu không truyền --raw-doc-code và không dùng --txt, parse mọi thư mục raw
    có cả source.txt và metadata.json. Kết quả audit nằm trong
    hierarchy.json.parser_metadata.
    """
    # 1.   Nếu dùng --txt để parse trực tiếp từ file text tự chọn
    if txt is not None:
        if not txt.exists():
            typer.echo(f"File text không tồn tại: {txt}", err=True)
            raise typer.Exit(code=1)
        if not raw_doc_code:
            typer.echo("Khi dùng --txt, bắt buộc phải truyền --raw-doc-code.", err=True)
            raise typer.Exit(code=1)

        metadata_path = settings.data_raw_dir / raw_doc_code / "metadata.json"
        if metadata_path.exists():
            try:
                doc_info = _document_info_from_metadata(_ready_metadata(raw_doc_code))
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=1) from exc
        else:
            typer.echo(
                "metadata.json hợp lệ là bắt buộc khi dùng --txt; không tạo hierarchy thiếu legal metadata.",
                err=True,
            )
            raise typer.Exit(code=1)

        text = txt.read_text(encoding="utf-8")
        try:
            parsed, diagnostics = parse_text_with_diagnostics(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        out_dir = settings.data_processed_dir / raw_doc_code
        _write_parse_artifacts(out_dir, parsed, text)
        typer.echo(
            f"Parsed {raw_doc_code}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}"
        )
        return

    # 2. Nếu không dùng --txt và truyền --raw-doc-code cụ thể để parse một thư mục
    if raw_doc_code is not None:
        raw_dir = _raw_dir(raw_doc_code)
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(
                f"Thiếu {source_path} hoặc {metadata_path} — chạy `crawl` trước (hoặc dùng --txt).",
                err=True,
            )
            raise typer.Exit(code=1)

        try:
            doc_info = _document_info_from_metadata(_ready_metadata(raw_doc_code))
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        provider_references = ensure_luatvietnam_reference_sidecar(raw_dir)
        text = source_path.read_text(encoding="utf-8")
        try:
            parsed, diagnostics = parse_text_with_diagnostics(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        out_dir = _processed_dir(raw_doc_code)
        _write_parse_artifacts(out_dir, parsed, text, provider_references)
        typer.echo(
            f"Parsed {raw_doc_code}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}"
        )
        return

    # 3. Nếu không truyền --txt/--raw-doc-code, parse mọi raw folder đầy đủ input.
    if not settings.data_raw_dir.exists():
        typer.echo(f"Thư mục nguồn {settings.data_raw_dir} không tồn tại.", err=True)
        raise typer.Exit(code=1)

    subdirs = [p for p in settings.data_raw_dir.iterdir() if p.is_dir()]
    valid_folders = [
        p.name
        for p in sorted(subdirs, key=lambda path: path.name)
        if (p / "source.txt").exists() and (p / "metadata.json").exists()
    ]

    if not valid_folders:
        typer.echo(
            "Không tìm thấy thư mục hợp lệ nào chứa cả source.txt và metadata.json trong data/raw/.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(
        f"Tìm thấy {len(valid_folders)} thư mục hợp lệ trong data/raw/. Bắt đầu parse song song..."
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    parsed_count = 0
    max_workers = min(10, len(valid_folders))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_folder = {
            executor.submit(_parse_folder_worker, folder_name): folder_name
            for folder_name in valid_folders
        }

        for future in as_completed(future_to_folder):
            folder_name = future_to_folder[future]
            try:
                success = future.result()
                if success:
                    parsed_count += 1
            except Exception as e:
                typer.echo(f"Lỗi không xác định khi xử lý {folder_name}: {e}", err=True)

    typer.echo(
        f"Hoàn thành parse hàng loạt: Đã parse {parsed_count}/{len(valid_folders)} thư mục."
    )


# Lệnh CLI để trích xuất thực thể, quan hệ từ cấu trúc đã phân tách sử dụng mô hình LLM.
@app.command()
def extract(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
    articles: Annotated[
        str | None,
        typer.Option(
            help="Comma-separated Article numbers for smoke extraction; omitted means full document."
        ),
    ] = None,
) -> None:
    """Chạy LLM Extraction + Validation + Scoring trên hierarchy.json đã parse."""
    try:
        settings.require_api_key()
    except Exception as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    hierarchy_path = _processed_dir(raw_doc_code) / "hierarchy.json"
    if not hierarchy_path.exists():
        typer.echo(f"Thiếu {hierarchy_path} — chạy `parse` trước.", err=True)
        raise typer.Exit(code=1)

    parsed = ParsedDocument.model_validate_json(
        hierarchy_path.read_text(encoding="utf-8")
    )
    selected = (
        {value.strip().lower() for value in articles.split(",") if value.strip()}
        if articles
        else None
    )
    try:
        run_pipeline(
            parsed,
            settings.data_processed_dir,
            raw_doc_code=raw_doc_code,
            article_numbers=selected,
            source_text=_read_canonical_source(raw_doc_code),
            diagram=_read_diagram(raw_doc_code),
        )
    except (ExtractionProviderError, ValueError) as exc:
        typer.echo(f"Extraction blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Extraction xong cho {raw_doc_code}: xem data/processed/{raw_doc_code}/"
        "{extract.jsonl, accepted.jsonl, review.jsonl, rejected.jsonl, entity_index.json}"
    )


@app.command("normalize-extraction")
def normalize_extraction(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
    articles: Annotated[
        str | None,
        typer.Option(
            help="Comma-separated checkpoint Article numbers; omitted means full document."
        ),
    ] = None,
) -> None:
    """Regenerate decision artifacts from valid per-Article checkpoints without LLM calls."""
    hierarchy_path = _processed_dir(raw_doc_code) / "hierarchy.json"
    if not hierarchy_path.exists():
        typer.echo(f"Thiếu {hierarchy_path} — chạy `parse` trước.", err=True)
        raise typer.Exit(code=1)
    parsed = ParsedDocument.model_validate_json(
        hierarchy_path.read_text(encoding="utf-8")
    )
    selected = (
        {value.strip().lower() for value in articles.split(",") if value.strip()}
        if articles
        else None
    )
    try:
        run_pipeline(
            parsed,
            settings.data_processed_dir,
            raw_doc_code=raw_doc_code,
            provider_calls_allowed=False,
            article_numbers=selected,
            source_text=_read_canonical_source(raw_doc_code),
            diagram=_read_diagram(raw_doc_code),
        )
    except (ExtractionProviderError, ValueError) as exc:
        typer.echo(f"Extraction normalization blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Decision artifacts regenerated from checkpoints for {raw_doc_code}")


@app.command("archive-extraction")
def archive_extraction(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
) -> None:
    """Archive current decision artifacts that must not enter the writer."""
    processed_dir = _processed_dir(raw_doc_code)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = processed_dir / "runs" / f"pre_endpoint_normalization_{timestamp}"
    names = (
        "extract.jsonl",
        "accepted.jsonl",
        "review.jsonl",
        "rejected.jsonl",
        "entity_index.json",
        "prettier_extract.json",
    )
    existing = [
        processed_dir / name for name in names if (processed_dir / name).exists()
    ]
    if not existing:
        typer.echo(
            f"Không có extraction artifacts để archive tại {processed_dir}", err=True
        )
        raise typer.Exit(code=1)
    archive_dir.mkdir(parents=True, exist_ok=False)
    for source in existing:
        shutil.move(str(source), archive_dir / source.name)

    def _line_count(name: str) -> int:
        path = archive_dir / name
        return (
            sum(
                1
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            if path.exists()
            else 0
        )

    entity_path = archive_dir / "entity_index.json"
    entity_total = (
        len(json.loads(entity_path.read_text(encoding="utf-8")))
        if entity_path.exists()
        else 0
    )
    manifest = {
        "status": "invalid_for_write",
        "reason": "accepted records contain unresolved noncanonical structural endpoints",
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "raw_doc_code": raw_doc_code,
        "files": [path.name for path in existing],
        "counts": {
            "extracted": _line_count("extract.jsonl"),
            "accepted": _line_count("accepted.jsonl"),
            "review": _line_count("review.jsonl"),
            "rejected": _line_count("rejected.jsonl"),
            "entities": entity_total,
        },
        "known_failure": "Accepted relation references missing entity: khoan_1_1",
        "unresolved_endpoint_ids": 189,
        "unresolved_endpoint_references": 718,
    }
    (archive_dir / "audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    typer.echo(f"Archived invalid extraction artifacts to {archive_dir}")


@app.command("validate-data")
def validate_data(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
) -> None:
    """Validate curated metadata and canonical graph identity before parsing."""
    readiness = validate_document_readiness(
        raw_doc_code,
        settings.data_raw_dir,
        manifest_path=settings.curated_manifest_path,
    )
    if not readiness.valid:
        for error in readiness.errors:
            typer.echo(f"Data readiness error: {error}", err=True)
        raise typer.Exit(code=1)
    metadata = readiness.normalized_metadata
    typer.echo(
        json.dumps(
            {
                "raw_doc_code": raw_doc_code,
                "graph_id": metadata["graph_id"],
                "doc_type": metadata["doc_type"],
                "legal_status": metadata["legal_status"],
                "effective_from": metadata["effective_from"],
                "issuer_name": metadata["issuer_name"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("validate-payload")
def validate_payload(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
    mode: Annotated[
        str,
        typer.Option(help="Validation mode: 'full' (Gate 2 + structure) or 'structural' (Gate 1 only)"),
    ] = "full",
) -> None:
    """Build and validate a graph payload without opening a Neo4j connection."""
    processed_dir = _processed_dir(raw_doc_code)
    try:
        if mode == "structural":
            validate_structural_readiness(processed_dir)
        else:
            validate_extraction_readiness(processed_dir)
    except (ExtractionReadinessError, StructuralReadinessError) as exc:
        typer.echo(f"Readiness error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        payload = build_payload_from_paths(processed_dir, mode=mode)
    except PayloadBuildError as exc:
        typer.echo(f"Payload build error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    node_counts = Counter(node.get("type") for node in payload.get("nodes", []))
    relation_counts = Counter(
        relation.get("type") for relation in payload.get("relations", [])
    )

    consistency = validate_payload_consistency(payload)
    dangling_endpoint_count = sum(
        1 for err in consistency.errors if "dangling" in err.lower()
    )

    ontology_violation_count = 0
    ontology_errors = []
    try:
        validate_graph_payload(payload)
    except GraphValidationError as exc:
        ontology_errors = exc.errors
        ontology_violation_count = len(exc.errors)

    report = {
        "raw_doc_code": raw_doc_code,
        "graph_id": _graph_id(payload),
        "node_count_by_label": dict(sorted(node_counts.items())),
        "relation_count_by_type": dict(sorted(relation_counts.items())),
        "embedding_target_count": len(embedding_texts_by_node_id(payload)),
        "duplicate_node_id_count": consistency.duplicate_node_id_count,
        "duplicate_relation_identity_count": consistency.duplicate_relation_identity_count,
        "dangling_endpoint_count": dangling_endpoint_count,
        "ontology_violation_count": ontology_violation_count,
    }
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))

    has_errors = not consistency.valid or ontology_violation_count > 0
    if has_errors:
        for err in consistency.errors:
            typer.echo(f"Consistency error: {err}", err=True)
        for err in ontology_errors:
            typer.echo(f"Ontology error: {err}", err=True)
        raise typer.Exit(code=1)


@app.command("build-reference-registry")
def build_reference_registry(
    build_id: Annotated[
        str, typer.Option(help="Immutable registry build receipt ID")
    ] = "build_latest",
    raw_doc_code: Annotated[
        list[str] | None,
        typer.Option(help="Repeat for each explicitly selected processed document"),
    ] = None,
    manifest: Annotated[
        Path | None,
        typer.Option(
            help="Explicit corpus manifest; mutually exclusive with --raw-doc-code"
        ),
    ] = None,
    raw_dir: Annotated[
        Path | None,
        typer.Option(help="Raw corpus root used to load canonical source.txt files"),
    ] = None,
) -> None:
    """Build an immutable accepted-structure registry without Neo4j or LLM calls."""
    if bool(raw_doc_code) == bool(manifest):
        typer.echo(
            "Provide either repeated --raw-doc-code or --manifest, but not both.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        selected = (
            list(dict.fromkeys(raw_doc_code or []))
            if manifest is None
            else list(load_curated_manifest(manifest))
        )
    except Exception as exc:
        typer.echo(f"Registry selection error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payloads = {}
    sources = {}
    try:
        for code in selected:
            logger.info("Registry build: validating %s", code)
            loaded = load_validated_payload(_processed_dir(code))
            source_path = (raw_dir or settings.data_raw_dir) / code / "source.txt"
            if not source_path.is_file():
                raise ValidatedPayloadLoadError(
                    f"Missing canonical source: {source_path}"
                )
            payloads[code] = loaded.validated_payload
            sources[code] = source_path.read_text(encoding="utf-8")
        build_dir = settings.data_registry_dir / "builds" / build_id
        if build_dir.exists():
            import shutil

            shutil.rmtree(build_dir, ignore_errors=True)
        build = build_corpus_registry(payloads, sources, build_id=build_id)
        publish_registry_build(build, settings.data_registry_dir)
    except (ValidatedPayloadLoadError, RegistryError, OSError, ValueError) as exc:
        typer.echo(f"Registry build blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "build_id": build.receipt.build_id,
                "snapshot_hash": build.receipt.snapshot_hash,
                "provenance_hash": build.receipt.provenance_hash,
                "document_count": build.registry.manifest.document_count,
                "structural_unit_count": build.registry.manifest.structural_unit_count,
                "contains_relation_count": build.registry.manifest.contains_relation_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("reconcile-external-references")
def reconcile_external_reference_command(
    build_id: Annotated[str, typer.Option(help="Verified registry build receipt ID")],
    raw_doc_code: Annotated[
        list[str], typer.Option(help="Repeat for each source document to reconcile")
    ],
    apply: Annotated[
        bool, typer.Option(help="Write verified REFERS_TO edges to Neo4j")
    ] = False,
    raw_dir: Annotated[
        Path | None,
        typer.Option(help="Raw corpus root used to load canonical source.txt files"),
    ] = None,
) -> None:
    """Resolve external citations; graph writes require explicit --apply."""
    try:
        build = load_registry_build(settings.data_registry_dir, build_id)
    except (RegistryError, OSError, ValueError) as exc:
        typer.echo(f"Registry load blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    session = create_neo4j_session() if apply else None
    reports = []
    try:
        for code in dict.fromkeys(raw_doc_code):
            processed_dir = _processed_dir(code)
            hierarchy_path = processed_dir / "hierarchy.json"
            source_path = (raw_dir or settings.data_raw_dir) / code / "source.txt"
            if not hierarchy_path.is_file() or not source_path.is_file():
                raise ValueError(
                    f"Missing hierarchy/source for {code}; run parse and normalization first"
                )
            parsed = ParsedDocument.model_validate_json(
                hierarchy_path.read_text(encoding="utf-8")
            )
            logger.info(
                "External reference reconciliation: %s (%s)",
                code,
                "apply" if apply else "dry-run",
            )
            report = reconcile_external_reference_service(
                raw_doc_code=code,
                processed_dir=processed_dir,
                parsed=parsed,
                source_text=source_path.read_text(encoding="utf-8"),
                build=build,
                apply=apply,
                session=session,
            )
            reports.append(report)
    except Exception as exc:
        typer.echo(f"External reconciliation blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if session is not None:
            session.close()
    payload = [asdict(report) for report in reports]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if apply and any(
        report.failed_count
        or report.blocked_count
        or report.provider_projected_requires_rebuild_count
        or report.provider_temporal_not_accepted_count
        for report in reports
    ):
        raise typer.Exit(code=1)


@app.command("reference-status")
def reference_status_command(
    raw_doc_code: Annotated[str, typer.Option(help="Processed source document code")],
) -> None:
    """Print stable JSON resolution/materialization checkpoint metrics."""
    try:
        report = load_reference_status(_processed_dir(raw_doc_code))
    except Exception as exc:
        typer.echo(f"Reference status blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {"raw_doc_code": raw_doc_code, **report},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


@app.command("write")
def write_graph(
    raw_doc_code: Annotated[
        str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")
    ],
    mode: Annotated[
        str,
        typer.Option(help="Write mode: 'full' (default) or 'structural' (only Document hierarchy)"),
    ] = "full",
) -> None:
    """Build accepted graph payload and write it to Neo4j through the guarded writer."""
    payload = _validated_payload_for_raw_doc_code(raw_doc_code, mode=mode)
    session = create_neo4j_session()
    try:
        service = GraphIngestionService(
            writer=Neo4jWriter(session=session),
            hierarchy_reconciler=SectionHierarchyReconciler(session=session),
        )
        validated_payload = service.ingest(payload)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    typer.echo(
        f"Wrote graph ({mode}) for {raw_doc_code}: "
        f"{len(validated_payload.nodes)} nodes, {len(validated_payload.relations)} relations"
    )
    hierarchy_report = service.last_hierarchy_report
    if hierarchy_report is not None:
        typer.echo(
            "Section hierarchy reconciliation: "
            f"{hierarchy_report.mapping_count} mapped Article(s), "
            f"{hierarchy_report.deleted_legacy_edge_count} legacy edge(s) removed"
        )


@app.command("add-node")
@app.command("write-node")
@app.command("write-structural")
def write_graph_structural(
    raw_doc_code: Annotated[
        str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")
    ],
) -> None:
    """Ghi các node cấu trúc (Document/Article/Clause/Point/Appendix...) của 1 raw_doc_code vào Neo4j (Phase 1)."""
    write_graph(raw_doc_code=raw_doc_code, mode="structural")


@app.command("sync-concept")
@app.command("sync-concepts")
@app.command("sync-semantics")
@app.command("enrich-semantics")
def sync_concepts(
    raw_doc_code: Annotated[
        str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")
    ],
) -> None:
    """Đồng bộ các thực thể ngữ nghĩa (LegalConcept, LegalSubject, LegalAction) và quan hệ của 1 raw_doc_code vào Neo4j (Phase 2)."""
    write_graph(raw_doc_code=raw_doc_code, mode="full")


@app.command("embed-node")
@app.command("embed")
def embed_graph(
    raw_doc_code: Annotated[
        str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")
    ],
    batch_size: Annotated[int, typer.Option(min=1, help="Embedding batch size")] = 32,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Verify vector indexes and report stale targets without loading the model or writing Neo4j",
        ),
    ] = False,
) -> None:
    """Generate and write configured-dimension Appendix/Article/Clause embeddings."""
    payload = _validated_payload_for_raw_doc_code(raw_doc_code)
    texts_by_node_id = embedding_texts_by_node_id(payload)
    graph_id = _graph_id(payload)
    content_hashes = {
        node_id: embedding_content_hash(text)
        for node_id, text in texts_by_node_id.items()
    }

    session = create_neo4j_session()
    try:
        writer = Neo4jEmbeddingWriter(session=session)
        writer.verify_vector_indexes()
        stale_ids = writer.stale_target_ids(
            graph_id,
            content_hashes,
            model=settings.embedding_model,
            provider=settings.embedding_provider,
            normalized=True,
        )
        if dry_run:
            typer.echo(
                f"Embedding readiness for {raw_doc_code}: "
                f"targets={len(texts_by_node_id)}, stale={len(stale_ids)}, "
                f"current={len(texts_by_node_id) - len(stale_ids)}, "
                f"model={settings.embedding_model}, "
                f"provider={settings.embedding_provider}, "
                f"dimension={settings.embedding_dimension}"
            )
            return
        generator = EmbeddingGenerator()
        for start in range(0, len(stale_ids), batch_size):
            batch_ids = stale_ids[start : start + batch_size]
            vectors = generator.encode(
                [texts_by_node_id[node_id] for node_id in batch_ids]
            )
            writer.write_embeddings(
                dict(zip(batch_ids, vectors, strict=True)),
                graph_id=graph_id,
                content_hashes={
                    node_id: content_hashes[node_id] for node_id in batch_ids
                },
                model=settings.embedding_model,
                provider=settings.embedding_provider,
                normalized=True,
            )
            typer.echo(
                f"Embedded {min(start + len(batch_ids), len(stale_ids))}/{len(stale_ids)} stale targets"
            )
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    typer.echo(
        f"Embedding complete for {raw_doc_code}: updated={len(stale_ids)}, skipped={len(texts_by_node_id) - len(stale_ids)}"
    )


@app.command("graph-quality")
def graph_quality(
    raw_doc_code: Annotated[
        str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")
    ],
) -> None:
    """Generate graph quality metrics from the canonical graph payload."""
    processed_dir = _processed_dir(raw_doc_code)
    try:
        validate_extraction_readiness(processed_dir)
    except ExtractionReadinessError as exc:
        typer.echo(f"Extraction readiness error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    hierarchy_path = processed_dir / "hierarchy.json"
    if not hierarchy_path.exists():
        typer.echo(f"Thiếu {hierarchy_path} — chạy `parse` trước.", err=True)
        raise typer.Exit(code=1)
    parsed = ParsedDocument.model_validate_json(
        hierarchy_path.read_text(encoding="utf-8")
    )

    session = create_neo4j_session()
    try:
        report = GraphQualityReporter(session=session).generate_for_document(
            graph_id=parsed.document.id
        )
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    report["extraction_decisions"] = decision_stats_from_paths(
        _processed_dir(raw_doc_code)
    )
    report["external_references"] = load_reference_status(_processed_dir(raw_doc_code))
    out_dir = settings.data_reports_dir / raw_doc_code
    write_graph_quality_report(report, out_dir)
    typer.echo(f"Wrote graph quality report -> {out_dir}")


@app.command("verify-m3-schema")
def verify_m3_schema() -> None:
    """Verify the canonical schema on the dedicated disposable M3 database."""
    try:
        safe_uri = validate_disposable_uri(settings.neo4j_uri)
    except M3RuntimeGuardError as exc:
        typer.echo(f"M3 runtime guard error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    session = create_neo4j_session()
    try:
        report = verify_canonical_schema(session)
    except SchemaVerificationError as exc:
        typer.echo(f"Schema verification error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        session.close()
    typer.echo(
        json.dumps(
            {
                "uri": safe_uri,
                "constraints": report.constraints,
                "indexes": report.user_indexes,
            },
            indent=2,
        )
    )


@app.command("graph-snapshot")
def graph_snapshot(
    raw_doc_code: Annotated[
        str, typer.Option(help="Filesystem document code, vd 'L59_2020'")
    ],
    output: Annotated[
        str | None, typer.Option(help="Evidence file name under snapshots/")
    ] = None,
) -> None:
    """Capture a read-only payload-to-graph digest snapshot from disposable Neo4j."""
    try:
        safe_uri = validate_disposable_uri(settings.neo4j_uri)
    except M3RuntimeGuardError as exc:
        typer.echo(f"M3 runtime guard error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    payload = _validated_payload_for_raw_doc_code(raw_doc_code)
    graph_id = _graph_id(payload)
    session = create_neo4j_session()
    try:
        snapshot = generate_snapshot(session, payload, graph_id=graph_id, uri=safe_uri)
    finally:
        session.close()
    output_name = output or datetime.now(timezone.utc).strftime(
        "snapshot_%Y%m%dT%H%M%SZ.json"
    )
    try:
        path = write_snapshot(
            snapshot,
            settings.data_reports_dir / raw_doc_code / "snapshots",
            output_name,
        )
    except ValueError as exc:
        typer.echo(f"Snapshot output error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wrote graph snapshot -> {path}")


@app.command("vector-smoke")
def vector_smoke(
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code")],
) -> None:
    """Run the fixed top-5 Milestone A queries against both vector indexes."""
    try:
        validate_disposable_uri(settings.neo4j_uri)
    except M3RuntimeGuardError as exc:
        typer.echo(f"M3 runtime guard error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    vectors = EmbeddingGenerator().encode(list(SMOKE_QUERIES.values()))
    session = create_neo4j_session()
    try:
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()
        report = run_vector_smoke(session, vectors, k=5)
    finally:
        session.close()
    results_path, judgements_path = write_vector_smoke_evidence(
        report, settings.data_reports_dir / raw_doc_code / "vector_smoke"
    )
    typer.echo(f"Vector smoke results -> {results_path}")
    typer.echo(f"Manual judgement template -> {judgements_path}")


@app.command("milestone-a-report")
def milestone_a_report(
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code")],
) -> None:
    """Validate pilot evidence without promoting the four-document corpus gate."""
    try:
        report = generate_milestone_a_report(raw_doc_code, settings.data_reports_dir)
    except MilestoneAReportError as exc:
        typer.echo(f"Milestone A evidence error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    json_path, md_path = write_milestone_a_report(
        report, settings.data_reports_dir / raw_doc_code
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    typer.echo(f"Report JSON -> {json_path}")
    typer.echo(f"Report Markdown -> {md_path}")
    if not report["pilot_evidence_pass"]:
        raise typer.Exit(code=1)


def _validated_payload_for_raw_doc_code(
    raw_doc_code: str, *, mode: str = "full"
) -> dict:
    processed_dir = _processed_dir(raw_doc_code)
    try:
        return load_validated_payload(processed_dir, mode=mode).raw_payload
    except ValidatedPayloadLoadError as exc:
        if mode == "full" and (processed_dir / "hierarchy.json").exists():
            try:
                return load_validated_payload(processed_dir, mode="structural").raw_payload
            except Exception:
                pass
        typer.echo(f"Validated payload load error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _graph_id(payload: dict) -> str:
    for node in payload.get("nodes", []):
        if node.get("type") == "Document":
            return str(node["id"])
    raise typer.BadParameter("Payload has no Document node")


# Lệnh CLI để chạy toàn bộ luồng tích hợp: cào dữ liệu, phân tách cấu trúc, trích xuất tri thức, nạp Neo4j và tạo embedding.
@app.command()
def ingest(
    url: Annotated[
        str, typer.Option(help="URL trang chi tiết (luatvietnam.vn hoặc vbpl.vn)")
    ],
    raw_doc_code: Annotated[
        str | None,
        typer.Option(
            help="Filesystem document code, vd 'L59_2020'. Tùy chọn (tự sinh nếu để trống)"
        ),
    ] = None,
    number: Annotated[
        str | None, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'. Tùy chọn")
    ] = None,
    write_neo4j: Annotated[
        bool, typer.Option(help="Tự động ghi đồ thị vào Neo4j")
    ] = True,
    generate_embedding: Annotated[
        bool, typer.Option(help="Tự động tạo BGE-M3 embedding vào Neo4j")
    ] = True,
    skip_extract: Annotated[
        bool,
        typer.Option(
            "--skip-extract",
            help="Bỏ qua trích xuất LLM, chỉ nạp khung cấu trúc và tạo embedding",
        ),
    ] = False,
) -> None:
    """Full pipeline: crawl -> parse -> [extract] -> write -> embed."""
    saved_dir = crawl(url, raw_doc_code, number)
    code = raw_doc_code or saved_dir.name
    parse(code)
    if not skip_extract:
        extract(code)
    if write_neo4j:
        try:
            write_mode = "structural" if skip_extract else "full"
            write_graph(code, mode=write_mode)
        except Exception as exc:
            typer.echo(f"Bỏ qua write Neo4j: {exc}", err=True)
    if generate_embedding and write_neo4j:
        try:
            embed_graph(code)
        except Exception as exc:
            typer.echo(f"Bỏ qua embed: {exc}", err=True)


# 1. Lệnh CLI sinh file manifest chuẩn cho dataset
@app.command()
def build_manifest(
    raw_dir: Annotated[
        Path, typer.Option(help="Thư mục lưu trữ dataset thô")
    ] = settings.luatvietnam_raw_dir,
    output: Annotated[
        Path, typer.Option(help="Đường dẫn xuất file manifest JSON")
    ] = settings.luatvietnam_manifest_path,
) -> None:
    """Tự động quét raw_dir, chuẩn hóa metadata và tạo file manifest JSON."""
    count = generate_manifest_file(raw_dir, output)
    typer.echo(f"Đã tạo file manifest thành công cho {count} văn bản tại: {output}")


# 2. Lệnh CLI parse cấu trúc hàng loạt (Batch Parse)
@app.command()
def batch_parse(
    manifest: Annotated[
        Path, typer.Option(help="Đường dẫn file manifest JSON")
    ] = settings.luatvietnam_manifest_path,
    raw_dir: Annotated[
        Path, typer.Option(help="Thư mục lưu trữ dataset thô")
    ] = settings.luatvietnam_raw_dir,
    workers: Annotated[
        int, typer.Option(min=1, max=128, help="Số lượng luồng xử lý song song")
    ] = 4,
    retry_failed: Annotated[
        bool, typer.Option(help="Chạy lại các văn bản từng gặp lỗi")
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý (vd: --limit 3 để test)"),
    ] = None,
) -> None:
    """Parse cấu trúc cây (Chương/Mục/Điều/Khoản/Điểm) cho toàn bộ dataset trong manifest."""
    if (raw_dir / "metadata.json").exists() or (raw_dir / "source.txt").exists():
        raw_dir = raw_dir.parent

    manifest_data = load_curated_manifest(manifest)
    doc_codes = list(manifest_data.keys())
    selected_codes = doc_codes[:limit] if limit and limit > 0 else doc_codes

    # Lọc các văn bản cần parse (hỗ trợ checkpoint resuming)
    pending_codes = filter_documents_for_step(
        selected_codes, step="parse", retry_failed=retry_failed
    )

    typer.echo(
        f"Tổng số văn bản trong manifest: {len(doc_codes)}. Cần parse: {len(pending_codes)}"
    )

    refresh_codes = selected_codes
    if not pending_codes:
        _rebuild_provider_candidates_after_batch_parse(refresh_codes, raw_root=raw_dir)
        typer.echo(
            "Tất cả văn bản đã được parse; provider candidates đã được đối soát lại."
        )
        return

    success_count = 0
    fail_count = 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(
                _parse_folder_worker, code, raw_root=raw_dir, manifest_path=manifest
            ): code
            for code in pending_codes
        }
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                ok = future.result()
                if ok:
                    success_count += 1
                    record_doc_status(code, step="parse", status="SUCCESS")
                else:
                    fail_count += 1
                    record_doc_status(
                        code, step="parse", status="FAILED", error="Parse failed"
                    )
            except Exception as exc:
                fail_count += 1
                record_doc_status(code, step="parse", status="FAILED", error=str(exc))

    _rebuild_provider_candidates_after_batch_parse(refresh_codes, raw_root=raw_dir)
    typer.echo(
        f"Hoàn thành Batch Parse. Thành công: {success_count}, Thất bại: {fail_count}"
    )
    if fail_count:
        raise typer.Exit(code=1)


# 3. Lệnh CLI extract tri thức LLM hàng loạt (Batch Extract)
@app.command()
def batch_extract(
    manifest: Annotated[
        Path, typer.Option(help="Đường dẫn file manifest JSON")
    ] = settings.luatvietnam_manifest_path,
    raw_dir: Annotated[
        Path, typer.Option(help="Thư mục lưu trữ dataset thô")
    ] = settings.luatvietnam_raw_dir,
    workers: Annotated[
        int, typer.Option(help="Số lượng văn bản xử lý song song", min=1, max=32)
    ] = 4,
    retry_failed: Annotated[
        bool, typer.Option(help="Chạy lại các văn bản từng gặp lỗi")
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý (vd: --limit 3 để test)"),
    ] = None,
) -> None:
    """Gọi LLM trích xuất tri thức song song cho tập dữ liệu trong manifest (hỗ trợ Article Checkpoint)."""
    if (raw_dir / "metadata.json").exists() or (raw_dir / "source.txt").exists():
        raw_dir = raw_dir.parent
    manifest_data = load_curated_manifest(manifest)
    doc_codes = list(manifest_data.keys())

    filtered_codes = filter_documents_for_step(
        doc_codes, step="extract", retry_failed=retry_failed
    )
    pending_codes = [
        code
        for code in doc_codes
        if code in filtered_codes
        or not (_processed_dir(code) / "extract.jsonl").exists()
    ]
    if limit and limit > 0:
        pending_codes = pending_codes[:limit]

    typer.echo(
        f"Tổng số văn bản trong manifest: {len(doc_codes)}. Cần extract: {len(pending_codes)}"
    )

    if not pending_codes:
        typer.echo("Tất cả văn bản đã extract tri thức xong.")
        return

    def _extract_single_doc(code: str) -> bool:
        try:
            processed_dir = _processed_dir(code)
            hierarchy_path = processed_dir / "hierarchy.json"
            if not hierarchy_path.exists():
                _parse_folder_worker(code, raw_root=raw_dir, manifest_path=manifest)

            parsed = ParsedDocument.model_validate_json(
                hierarchy_path.read_text(encoding="utf-8")
            )
            raw_doc_dir = (
                raw_dir / code
                if (raw_dir / code).exists()
                else settings.data_raw_dir / code
            )
            source_file = raw_doc_dir / "source.txt"
            source_text = (
                source_file.read_text(encoding="utf-8")
                if source_file.exists()
                else None
            )

            diagram = _read_diagram(code, raw_root=raw_dir)
            run_pipeline(
                parsed,
                settings.data_processed_dir,
                raw_doc_code=code,
                source_text=source_text,
                diagram=diagram,
            )
            record_doc_status(code, step="extract", status="SUCCESS")
            typer.echo(f"Extract thành công [{code}]")
            return True
        except Exception as exc:
            typer.echo(f"Lỗi extract [{code}]: {exc}", err=True)
            record_doc_status(code, step="extract", status="FAILED", error=str(exc))
            return False

    success_count = 0
    fail_count = 0

    if workers == 1:
        for code in pending_codes:
            if _extract_single_doc(code):
                success_count += 1
            else:
                fail_count += 1
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {
                executor.submit(_extract_single_doc, code): code
                for code in pending_codes
            }
            for future in as_completed(future_to_code):
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1

    typer.echo(
        f"Hoàn thành Batch Extract. Thành công: {success_count}, Thất bại: {fail_count}"
    )


def _discover_processed_doc_codes(
    processed_root: Path,
    manifest_path: Path | None = None,
    limit: int | None = None,
) -> list[str]:
    # 1.   If manifest is provided and exists, load doc_codes from manifest
    if manifest_path is not None and manifest_path.exists():
        manifest_data = load_curated_manifest(manifest_path)
        codes = [
            code
            for code in manifest_data.keys()
            if (processed_root / code / "hierarchy.json").exists()
        ]
    else:
        # 2.   Otherwise, scan processed directory for all folders with hierarchy.json
        if not processed_root.exists():
            return []
        codes = [
            sub.name
            for sub in sorted(processed_root.iterdir())
            if sub.is_dir() and (sub / "hierarchy.json").exists()
        ]
    if limit is not None and limit > 0:
        codes = codes[:limit]
    return codes


# Lệnh CLI ghi đồ thị hàng loạt các văn bản đã parse vào Neo4j
@app.command("batch-add-nodes")
@app.command("batch-write-nodes")
@app.command("batch-write")
def batch_write(
    processed_dir: Annotated[
        Path,
        typer.Option(help="Thư mục chứa các folder processed (mặc định: data/processed)"),
    ] = settings.data_processed_dir,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Đường dẫn file manifest JSON (tùy chọn để lọc danh sách)"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(help="Chế độ write: 'structural' (mặc định) hoặc 'full'"),
    ] = "structural",
    workers: Annotated[
        int,
        typer.Option(min=1, max=32, help="Số lượng luồng ghi song song vào Neo4j"),
    ] = 4,
    skip_existing: Annotated[
        bool,
        typer.Option(
            "--skip-existing",
            help="Bỏ qua các văn bản đã có trên Neo4j (Checkpoint thông minh)",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý"),
    ] = None,
) -> None:
    """Ghi hàng loạt toàn bộ folder processed nodes (cấu trúc phân cấp) vào Neo4j."""
    # 1.   Quét danh sách các văn bản đã parse
    doc_codes = _discover_processed_doc_codes(processed_dir, manifest_path=manifest, limit=limit)
    if not doc_codes:
        typer.echo(f"Không tìm thấy văn bản nào có hierarchy.json trong {processed_dir}")
        return

    # 2.   Nếu bật --skip-existing, truy vấn danh sách văn bản đã có trên Neo4j
    if skip_existing:
        session = create_neo4j_session()
        try:
            res = session.run("MATCH (d:Document) RETURN d.id AS id").data()
            existing_ids = {r["id"] for r in res}
            # Lọc bỏ các doc_code đã nạp
            original_len = len(doc_codes)
            doc_codes = [c for c in doc_codes if c not in existing_ids]
            skipped_count = original_len - len(doc_codes)
            if skipped_count > 0:
                typer.echo(f"⏩ [Checkpoint] Đã bỏ qua {skipped_count} văn bản đã có trên Neo4j.")
        except Exception as exc:
            typer.echo(f"⚠️ Không thể lấy danh sách Document hiện tại ({exc}), tiếp tục nạp bình thường.")
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    if not doc_codes:
        typer.echo("🎉 Tất cả văn bản đã tồn tại trên Neo4j. Không có văn bản nào cần nạp mới!")
        return

    typer.echo(f"🚀 Bắt đầu Batch Write ({mode}) cho {len(doc_codes)} văn bản với {workers} luồng...")
    success_count = 0
    fail_count = 0

    def _write_single_doc(code: str) -> bool:
        typer.echo(f"⏳ [Luồng bắt đầu] Writing {code}...")
        try:
            write_graph(code, mode=mode)
            typer.echo(f"✅ [Hoàn thành] Wrote {code}")
            return True
        except Exception as exc:
            typer.echo(f"❌ [Lỗi] write {code}: {exc}", err=True)
            return False

    # 2.   Thực hiện write theo luồng
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {executor.submit(_write_single_doc, code): code for code in doc_codes}
            for future in as_completed(future_to_code):
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1
    else:
        for code in doc_codes:
            if _write_single_doc(code):
                success_count += 1
            else:
                fail_count += 1

    typer.echo(f"\n🎉 Hoàn thành Batch Write. Thành công: {success_count}, Thất bại: {fail_count}")


# Lệnh CLI tạo Vector Embedding hàng loạt cho các văn bản đã parse
@app.command("batch-embed-nodes")
@app.command("batch-embed")
def batch_embed(
    processed_dir: Annotated[
        Path,
        typer.Option(help="Thư mục chứa các folder processed (mặc định: data/processed)"),
    ] = settings.data_processed_dir,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Đường dẫn file manifest JSON (tùy chọn để lọc danh sách)"),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(min=1, help="Embedding batch size"),
    ] = 32,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý"),
    ] = None,
) -> None:
    """Sinh vector embeddings hàng loạt cho toàn bộ các văn bản trong folder processed và ghi vào Neo4j."""
    # 1.   Quét danh sách các văn bản đã parse
    doc_codes = _discover_processed_doc_codes(processed_dir, manifest_path=manifest, limit=limit)
    if not doc_codes:
        typer.echo(f"Không tìm thấy văn bản nào có hierarchy.json trong {processed_dir}")
        return

    typer.echo(f"🚀 Bắt đầu Batch Embed cho {len(doc_codes)} văn bản...")
    success_count = 0
    fail_count = 0

    # 2.   Thực hiện embed từng văn bản
    for idx, code in enumerate(doc_codes, 1):
        typer.echo(f"[{idx}/{len(doc_codes)}] Embedding {code}...")
        try:
            embed_graph(code, batch_size=batch_size)
            success_count += 1
        except Exception as exc:
            typer.echo(f"❌ Lỗi embed {code}: {exc}", err=True)
            fail_count += 1

    typer.echo(f"\n🎉 Hoàn thành Batch Embed. Thành công: {success_count}, Thất bại: {fail_count}")


# Lệnh CLI nạp trọn gói hàng loạt văn bản ĐÃ PARSE (Write + Embed)
@app.command("batch-load-parsed")
def batch_load_parsed(
    processed_dir: Annotated[
        Path,
        typer.Option(help="Thư mục chứa các folder processed (mặc định: data/processed)"),
    ] = settings.data_processed_dir,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Đường dẫn file manifest JSON (tùy chọn)"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(help="Chế độ write: 'structural' (mặc định) hoặc 'full'"),
    ] = "structural",
    generate_embedding: Annotated[
        bool,
        typer.Option(help="Tự động tạo vector embeddings sau khi write"),
    ] = True,
    workers: Annotated[
        int,
        typer.Option(min=1, max=32, help="Số lượng luồng ghi song song vào Neo4j"),
    ] = 4,
    skip_existing: Annotated[
        bool,
        typer.Option(
            "--skip-existing",
            help="Bỏ qua các văn bản đã có trên Neo4j (Checkpoint thông minh)",
        ),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option(min=1, help="Embedding batch size"),
    ] = 32,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý"),
    ] = None,
) -> None:
    """Nạp nhanh hàng loạt các văn bản ĐÃ PARSE vào Neo4j (Write + Embed)."""
    typer.echo(f"=== BƯỚC 1/2: Ghi đồ thị hàng loạt ({mode}) vào Neo4j ===")
    batch_write(
        processed_dir=processed_dir,
        manifest=manifest,
        mode=mode,
        workers=workers,
        skip_existing=skip_existing,
        limit=limit,
    )

    if generate_embedding:
        typer.echo("\n=== BƯỚC 2/2: Tạo Vector Embedding hàng loạt ===")
        batch_embed(processed_dir=processed_dir, manifest=manifest, batch_size=batch_size, limit=limit)

    typer.echo("\n🎉 HOÀN THÀNH NẠP DỮ LIỆU ĐÃ PARSE VÀO NEO4J!")


def _discover_extraction_ready_doc_codes(
    processed_root: Path,
    manifest_path: Path | None = None,
    limit: int | None = None,
) -> list[str]:
    # 1.   If manifest is provided and exists, filter from manifest
    if manifest_path is not None and manifest_path.exists():
        manifest_data = load_curated_manifest(manifest_path)
        codes = [
            code
            for code in manifest_data.keys()
            if (processed_root / code / "accepted.jsonl").exists()
            and (processed_root / code / "entity_index.json").exists()
        ]
    else:
        # 2.   Otherwise, scan processed directory for folders having accepted.jsonl & entity_index.json
        if not processed_root.exists():
            return []
        codes = [
            sub.name
            for sub in sorted(processed_root.iterdir())
            if sub.is_dir()
            and (sub / "accepted.jsonl").exists()
            and (sub / "entity_index.json").exists()
        ]
    if limit is not None and limit > 0:
        codes = codes[:limit]
    return codes


# Lệnh CLI đồng bộ toàn bộ thực thể & quan hệ ngữ nghĩa hàng loạt vào Neo4j (Phase 2 Batch)
@app.command("batch-sync-concepts")
@app.command("batch-sync-semantics")
def batch_sync_semantics(
    processed_dir: Annotated[
        Path,
        typer.Option(help="Thư mục chứa các folder processed (mặc định: data/processed)"),
    ] = settings.data_processed_dir,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Đường dẫn file manifest JSON (tùy chọn để lọc danh sách)"),
    ] = None,
    workers: Annotated[
        int,
        typer.Option(min=1, max=32, help="Số lượng luồng đồng bộ song song vào Neo4j"),
    ] = 4,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý"),
    ] = None,
) -> None:
    """Đồng bộ hàng loạt toàn bộ thực thể ngữ nghĩa (LegalConcept, LegalSubject, LegalAction) vào Neo4j."""
    # 1.   Quét danh sách các văn bản đã có kết quả trích xuất
    doc_codes = _discover_extraction_ready_doc_codes(
        processed_dir, manifest_path=manifest, limit=limit
    )
    if not doc_codes:
        typer.echo(
            f"Không tìm thấy văn bản nào có accepted.jsonl và entity_index.json trong {processed_dir}"
        )
        return

    typer.echo(
        f"🚀 Bắt đầu Batch Sync Semantics cho {len(doc_codes)} văn bản với {workers} luồng..."
    )
    success_count = 0
    fail_count = 0

    def _sync_single_doc(code: str) -> bool:
        typer.echo(f"⏳ [Luồng bắt đầu] Syncing semantics for {code}...")
        try:
            write_graph(code, mode="full")
            typer.echo(f"✅ [Hoàn thành] Synced semantics for {code}")
            return True
        except Exception as exc:
            typer.echo(f"❌ [Lỗi] sync semantics {code}: {exc}", err=True)
            return False

    # 2.   Đồng bộ theo luồng vào Neo4j
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {executor.submit(_sync_single_doc, code): code for code in doc_codes}
            for future in as_completed(future_to_code):
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1
    else:
        for code in doc_codes:
            if _sync_single_doc(code):
                success_count += 1
            else:
                fail_count += 1

    typer.echo(
        f"\n🎉 Hoàn thành Batch Sync Semantics. Thành công: {success_count}, Thất bại: {fail_count}"
    )


# 4. Lệnh CLI chạy tuần tự TOÀN BỘ luồng Batch trong 1 câu lệnh (End-to-End Batch Ingest)
@app.command("batch-ingest-all")
def batch_ingest_all(
    manifest: Annotated[
        Path, typer.Option(help="Đường dẫn file manifest JSON")
    ] = settings.luatvietnam_manifest_path,
    raw_dir: Annotated[
        Path, typer.Option(help="Thư mục lưu trữ dataset thô")
    ] = settings.luatvietnam_raw_dir,
    workers: Annotated[
        int, typer.Option(min=1, max=32, help="Số lượng luồng xử lý song song")
    ] = 4,
    retry_failed: Annotated[
        bool, typer.Option(help="Chạy lại các văn bản từng gặp lỗi")
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý (vd: --limit 3 để test)"),
    ] = None,
    write_neo4j: Annotated[
        bool, typer.Option(help="Tự động ghi đồ thị vào Neo4j")
    ] = True,
    generate_embedding: Annotated[
        bool, typer.Option(help="Tự động tạo BGE-M3 embedding vào Neo4j")
    ] = True,
    skip_extract: Annotated[
        bool,
        typer.Option(
            "--skip-extract",
            help="Bỏ qua trích xuất LLM, chỉ nạp khung cấu trúc và tạo embedding",
        ),
    ] = False,
) -> None:
    """Chạy tuần tự TOÀN BỘ luồng Batch trong 1 lệnh duy nhất: manifest -> parse -> [extract] -> registry -> write -> embed."""
    typer.echo("=== BƯỚC 1/6: Tạo Manifest Dataset ===")
    build_manifest(raw_dir, output=manifest)

    typer.echo("\n=== BƯỚC 2/6: Phân tách Cấu trúc Hàng loạt (Batch Parse) ===")
    batch_parse(
        manifest=manifest,
        raw_dir=raw_dir,
        workers=workers,
        retry_failed=retry_failed,
        limit=limit,
    )

    if not skip_extract:
        typer.echo("\n=== BƯỚC 3/6: Rút trích Tri thức LLM Hàng loạt (Batch Extract) ===")
        batch_extract(
            manifest=manifest, raw_dir=raw_dir, retry_failed=retry_failed, limit=limit
        )

    manifest_data = load_curated_manifest(manifest)
    doc_codes = list(manifest_data.keys())
    if limit and limit > 0:
        doc_codes = doc_codes[:limit]

    if write_neo4j:
        write_mode = "structural" if skip_extract else "full"
        typer.echo(f"\n=== BƯỚC 4/6: Ghi Node Đồ thị Hàng loạt ({write_mode}) vào Neo4j ===")
        for code in doc_codes:
            write_graph(code, mode=write_mode)

    typer.echo("\n=== BƯỚC 5/6: Đăng ký & Đối soát Dẫn chiếu Toàn bộ Corpus ===")
    build_reference_registry(manifest=manifest, raw_dir=raw_dir)
    reconcile_external_reference_command(
        build_id="build_latest",
        raw_doc_code=doc_codes,
        apply=write_neo4j,
        raw_dir=raw_dir,
    )

    if generate_embedding and write_neo4j:
        typer.echo("\n=== BƯỚC 6/6: Sinh BGE-M3 Embedding Hàng loạt ===")
        for code in doc_codes:
            try:
                embed_graph(code)
            except Exception as exc:
                typer.echo(f"Lỗi khi generate embedding cho {code}: {exc}", err=True)

    typer.echo("\n🎉 HOÀN THÀNH TOÀN BỘ LUỒNG BATCH INGEST!")


# 4b. Lệnh CLI chạy FULL PIPELINE cho một thư mục văn bản bất kỳ (Folder -> Parse -> LLM Extract -> Reconcile -> Write Neo4j -> Embed)
@app.command("ingest-folder")
@app.command("pipeline-folder")
def ingest_folder(
    folder: Annotated[
        Path,
        typer.Option(
            help="Đường dẫn thư mục chứa các thư mục văn bản thô (VD: data/raw hoặc custom_folder)"
        ),
    ] = settings.data_raw_dir,
    manifest: Annotated[
        Path | None,
        typer.Option(help="Đường dẫn file manifest JSON (tự tạo tự động nếu để trống)"),
    ] = None,
    workers: Annotated[
        int, typer.Option(min=1, max=32, help="Số lượng luồng xử lý song song")
    ] = 4,
    retry_failed: Annotated[
        bool, typer.Option(help="Chạy lại các văn bản từng gặp lỗi")
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Giới hạn số lượng văn bản xử lý (vd: --limit 3 để test)"),
    ] = None,
    write_neo4j: Annotated[
        bool, typer.Option(help="Tự động ghi đồ thị vào Neo4j")
    ] = True,
    generate_embedding: Annotated[
        bool, typer.Option(help="Tự động tạo BGE-M3 embedding vào Neo4j")
    ] = True,
    doc_by_doc: Annotated[
        bool,
        typer.Option(
            help="Xử lý trọn gói (Parse -> Extract -> Write Neo4j -> Embed) lần lượt cho từng văn bản một trước khi sang văn bản tiếp theo"
        ),
    ] = False,
    skip_extract: Annotated[
        bool,
        typer.Option(
            "--skip-extract",
            help="Bỏ qua trích xuất LLM, chỉ nạp khung cấu trúc và tạo embedding",
        ),
    ] = False,
) -> None:
    """Chạy FULL PIPELINE end-to-end cho một thư mục văn bản: Manifest -> Parse -> [LLM Extract] -> Reference Reconcile -> Write Neo4j -> BGE-M3 Embed."""
    # 1.   Xác định đường dẫn thư mục và file manifest
    raw_dir = folder.resolve()
    if not raw_dir.exists() or not raw_dir.is_dir():
        typer.echo(f"❌ Thư mục không tồn tại: {raw_dir}", err=True)
        raise typer.Exit(code=1)

    is_single_doc = (raw_dir / "metadata.json").exists() or (
        raw_dir / "source.txt"
    ).exists()
    base_raw_dir = raw_dir.parent if is_single_doc else raw_dir
    manifest_path = manifest or (
        _processed_dir(raw_dir.name) / "manifest.json"
        if is_single_doc
        else settings.data_processed_dir / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"🚀 BẮT ĐẦU CHẠY FULL PIPELINE CHO THƯ MỤC: {raw_dir}")

    # 2.   Bước 1: Tạo Manifest
    typer.echo("\n=== BƯỚC 1/6: Tạo Manifest Dataset ===")
    build_manifest(raw_dir, output=manifest_path)

    manifest_data = load_curated_manifest(manifest_path)
    doc_codes = list(manifest_data.keys())
    if limit and limit > 0:
        doc_codes = doc_codes[:limit]

    write_mode = "structural" if skip_extract else "full"

    # Xử lý tuần tự từng văn bản một (Document by Document End-to-End)
    if doc_by_doc:
        typer.echo(
            f"\n🔄 CHẾ ĐỘ XỬ LÝ TUẦN TỰ TỪNG VĂN BẢN (END-TO-END DOCUMENT BY DOCUMENT): {len(doc_codes)} văn bản"
        )
        for idx, code in enumerate(doc_codes, 1):
            typer.echo("\n--------------------------------------------------")
            typer.echo(f"📄 [{idx}/{len(doc_codes)}] ĐANG XỬ LÝ VĂN BẢN: {code}")
            typer.echo("--------------------------------------------------")
            try:
                # Parse
                parsed_ok = _parse_folder_worker(
                    code, raw_root=base_raw_dir, manifest_path=manifest_path
                )
                if not parsed_ok:
                    raise RuntimeError(f"Parse failed for {code}")

                # LLM Extract
                if not skip_extract:
                    processed_dir = _processed_dir(code)
                    hierarchy_path = processed_dir / "hierarchy.json"
                    if hierarchy_path.exists():
                        parsed = ParsedDocument.model_validate_json(
                            hierarchy_path.read_text(encoding="utf-8")
                        )
                        raw_doc_dir = (
                            base_raw_dir / code
                            if (base_raw_dir / code).exists()
                            else settings.data_raw_dir / code
                        )
                        source_file = raw_doc_dir / "source.txt"
                        source_text = (
                            source_file.read_text(encoding="utf-8")
                            if source_file.exists()
                            else None
                        )
                        diagram = _read_diagram(code, raw_root=base_raw_dir)
                        run_pipeline(
                            parsed,
                            settings.data_processed_dir,
                            raw_doc_code=code,
                            source_text=source_text,
                            diagram=diagram,
                        )

                # Write Neo4j
                if write_neo4j:
                    write_graph(code, mode=write_mode)

                # Embeddings
                if generate_embedding and write_neo4j:
                    embed_graph(code)

                typer.echo(f"✅ ĐÃ HOÀN THÀNH XỬ LÝ & NẠP NEO4J CHO VĂN BẢN: {code}")
                record_doc_status(code, step="pipeline", status="SUCCESS")
            except Exception as exc:
                typer.echo(f"❌ Lỗi khi xử lý văn bản {code}: {exc}", err=True)
                record_doc_status(
                    code, step="pipeline", status="FAILED", error=str(exc)
                )

        # Reconcile references only after every available endpoint has been written.
        build_reference_registry(manifest=manifest_path, raw_dir=base_raw_dir)
        reconcile_external_reference_command(
            build_id="build_latest",
            raw_doc_code=doc_codes,
            apply=write_neo4j,
            raw_dir=base_raw_dir,
        )

        typer.echo(f"\n🎉 HOÀN THÀNH TUẦN TỰ TOÀN BỘ VĂN BẢN CHO THƯ MỤC: {raw_dir}")
        return

    # 3.   Bước 2: Parse cấu trúc cây
    typer.echo("\n=== BƯỚC 2/6: Phân tách Cấu trúc Hàng loạt (Batch Parse) ===")
    batch_parse(
        manifest=manifest_path,
        raw_dir=base_raw_dir,
        workers=workers,
        retry_failed=retry_failed,
        limit=limit,
    )

    # 4.   Bước 3: LLM Extraction
    if not skip_extract:
        typer.echo("\n=== BƯỚC 3/6: Rút trích Tri thức LLM Hàng loạt (Batch Extract) ===")
        batch_extract(
            manifest=manifest_path,
            raw_dir=base_raw_dir,
            retry_failed=retry_failed,
            limit=limit,
        )

    # 5. Write all endpoints before relation-only reconciliation.
    if write_neo4j:
        typer.echo(f"\n=== BƯỚC 4/6: Ghi Node Đồ thị Hàng loạt ({write_mode}) vào Neo4j ===")
        for code in doc_codes:
            write_graph(code, mode=write_mode)

    # 6. Build one registry snapshot and reconcile provider/rule references.
    typer.echo("\n=== BƯỚC 5/6: Đăng ký & Đối soát Dẫn chiếu Toàn bộ Corpus ===")
    build_reference_registry(manifest=manifest_path, raw_dir=base_raw_dir)
    reconcile_external_reference_command(
        build_id="build_latest",
        raw_doc_code=doc_codes,
        apply=write_neo4j,
        raw_dir=base_raw_dir,
    )

    # 7.   Bước 6: Generate BGE-M3 Embeddings
    if generate_embedding and write_neo4j:
        typer.echo("\n=== BƯỚC 6/6: Sinh BGE-M3 Embedding Hàng loạt ===")
        for code in doc_codes:
            try:
                embed_graph(code)
            except Exception as exc:
                typer.echo(f"Lỗi khi generate embedding cho {code}: {exc}", err=True)

    typer.echo(f"\n🎉 HOÀN THÀNH TOÀN BỘ FULL PIPELINE CHO THƯ MỤC: {raw_dir}")


@app.command("init-schema")
def init_schema_command(
    uri: Annotated[str, typer.Option(help="Neo4j Bolt URI")] = "",
    user: Annotated[str, typer.Option(help="Neo4j User")] = "",
    password: Annotated[str, typer.Option(help="Neo4j Password")] = "",
) -> None:
    """Apply all canonical constraints and indexes from 01_schema_init.cypher to Neo4j."""
    from neo4j import GraphDatabase
    from src.infrastructure.neo4j.schema_initializer import initialize_canonical_schema
    from src.infrastructure.neo4j.schema_verifier import verify_canonical_schema

    bolt_uri = uri or settings.neo4j_uri
    neo_user = user or settings.neo4j_user
    neo_pass = password or settings.neo4j_password

    typer.echo(f"📐 Applying canonical Neo4j schema to {bolt_uri}...")
    driver = GraphDatabase.driver(bolt_uri, auth=(neo_user, neo_pass))
    try:
        result = initialize_canonical_schema(driver)
        typer.echo(
            f"Applied {result['applied_statements']}/{result['total_statements']} statements."
        )
        if result["errors"]:
            for err in result["errors"]:
                typer.echo(f"  Warning: {err}", err=True)

        with driver.session() as session:
            status = verify_canonical_schema(session)
        typer.echo(
            f"✅ Schema active: {len(status.constraints)} constraints, "
            f"{len(status.user_indexes)} indexes."
        )
    finally:
        driver.close()


@app.command("verify-schema")
def verify_schema_command(
    uri: Annotated[str, typer.Option(help="Neo4j Bolt URI")] = "",
    user: Annotated[str, typer.Option(help="Neo4j User")] = "",
    password: Annotated[str, typer.Option(help="Neo4j Password")] = "",
) -> None:
    """Verify that canonical constraints and indexes are present and online in Neo4j."""
    from neo4j import GraphDatabase
    from src.infrastructure.neo4j.schema_verifier import verify_canonical_schema

    bolt_uri = uri or settings.neo4j_uri
    neo_user = user or settings.neo4j_user
    neo_pass = password or settings.neo4j_password

    driver = GraphDatabase.driver(bolt_uri, auth=(neo_user, neo_pass))
    try:
        with driver.session() as session:
            status = verify_canonical_schema(session)
        typer.echo(
            f"✅ Schema verified on {bolt_uri}:\n"
            f"  - Constraints ({len(status.constraints)}/12): {sorted(status.constraints)}\n"
            f"  - Indexes ({len(status.user_indexes)}/34): {sorted(status.user_indexes)}"
        )
    finally:
        driver.close()


@app.command("clear-database")
@app.command("clean-database")
def clear_database_command(
    uri: Annotated[str, typer.Option(help="Neo4j Bolt URI")] = "",
    user: Annotated[str, typer.Option(help="Neo4j User")] = "",
    password: Annotated[str, typer.Option(help="Neo4j Password")] = "",
    force: Annotated[bool, typer.Option("--force", "-f", help="Bỏ qua xác nhận xóa")] = False,
) -> None:
    """Xóa toàn bộ nodes và relationships trong cơ sở dữ liệu Neo4j."""
    from neo4j import GraphDatabase

    bolt_uri = uri or settings.neo4j_uri
    neo_user = user or settings.neo4j_user
    neo_pass = password or settings.neo4j_password

    if not force:
        confirm = typer.confirm(f"⚠️ Bạn có CHẮC CHẮN muốn xóa toàn bộ data trên Neo4j ({bolt_uri})?")
        if not confirm:
            typer.echo("Đã hủy thao tác xóa.")
            return

    typer.echo(f"🗑️ Đang kết nối tới {bolt_uri} để xóa toàn bộ data...")
    driver = GraphDatabase.driver(bolt_uri, auth=(neo_user, neo_pass))
    try:
        with driver.session() as session:
            # 1.   Đếm số lượng node và quan hệ hiện tại
            count_res = session.run("MATCH (n) RETURN count(n) AS node_count").single()
            node_count = count_res["node_count"] if count_res else 0
            rel_res = session.run("MATCH ()-[r]->() RETURN count(r) AS rel_count").single()
            rel_count = rel_res["rel_count"] if rel_res else 0

            typer.echo(f"Tìm thấy: {node_count} nodes, {rel_count} relationships.")
            if node_count == 0 and rel_count == 0:
                typer.echo("✅ Database hiện tại đã trống.")
                return

            # 2.   Thực hiện xóa toàn bộ
            session.run("MATCH (n) DETACH DELETE n")
            typer.echo(f"✅ Đã xóa sạch toàn bộ {node_count} nodes và {rel_count} relationships trên Neo4j!")
    finally:
        driver.close()


if __name__ == "__main__":
    app()

