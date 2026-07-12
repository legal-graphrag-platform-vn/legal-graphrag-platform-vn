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
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.pipeline.config import settings
from src.pipeline.crawler.vbpl_crawler import crawl_and_save, crawl_by_search
from src.pipeline.extraction.providers.base import ExtractionProviderError
from src.infrastructure.embedding.embedding_generator import (
    EmbeddingGenerator,
    embedding_content_hash,
    embedding_texts_by_node_id,
)
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter
from src.infrastructure.neo4j.graph_snapshot import generate_snapshot, write_snapshot
from src.infrastructure.neo4j.m3_runtime import M3RuntimeGuardError, validate_disposable_uri
from src.infrastructure.neo4j.schema_verifier import SchemaVerificationError, verify_canonical_schema
from src.infrastructure.neo4j.vector_smoke import SMOKE_QUERIES, run_vector_smoke, write_vector_smoke_evidence
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import DocumentInfo, ParsedDocument
from src.infrastructure.neo4j.writer import GraphIngestionService, Neo4jWriter, create_neo4j_session, validate_graph_payload
from src.pipeline.persistence.payload_builder import PayloadBuildError, build_payload_from_paths
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
from src.pipeline.validation.extraction_readiness import (
    ExtractionReadinessError,
    validate_extraction_readiness,
)
from src.shared.ontology.payload_consistency_validator import validate_payload_consistency
from src.shared.ontology.validators import GraphValidationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer(help="Legal GraphRAG — Graph Construction Pipeline (Milestone 1+2)")


def _document_info_from_metadata(meta: dict) -> DocumentInfo:
    return DocumentInfo(
        id=meta["graph_id"],
        title=meta["title"],
        number=meta["number"],
        doc_type=meta.get("doc_type") or meta.get("type"),
        normative=meta.get("normative", True),
        issued_by=meta.get("issued_by"),
        issuer_name=meta.get("issuer_name") or meta.get("issued_by"),
        issued_date=meta.get("issued_date"),
        effective_from=meta.get("effective_from"),
        effective_to=meta.get("effective_to"),
        legal_status=meta["legal_status"],
    )


def _ready_metadata(raw_doc_code: str) -> dict:
    readiness = validate_document_readiness(
        raw_doc_code,
        settings.data_raw_dir,
        manifest_path=settings.curated_manifest_path,
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


def _parse_folder_worker(raw_doc_code: str) -> bool:
    """Worker xử lý parse cho 1 thư mục đơn lẻ."""
    try:
        raw_dir = settings.data_raw_dir / raw_doc_code
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(f"Thư mục {raw_doc_code} thiếu source.txt hoặc metadata.json", err=True)
            return False

        doc_info = _document_info_from_metadata(_ready_metadata(raw_doc_code))

        text = source_path.read_text(encoding="utf-8")
        try:
            parsed = parse_text(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        out_dir = settings.data_processed_dir / raw_doc_code
        out_dir.mkdir(parents=True, exist_ok=True)
        # Ghi đè file hierarchy.json nếu đã tồn tại
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed thành công {raw_doc_code} -> {out_dir / 'hierarchy.json'}")
        return True
    except Exception as e:
        typer.echo(f"Lỗi khi parse thư mục {raw_doc_code}: {e}", err=True)
        return False


# Lệnh CLI để cào thông tin chi tiết và nội dung văn bản pháp luật từ trang vbpl.vn.
@app.command()
def crawl(
    url: Annotated[str, typer.Option(help="URL trang chi tiết vbpl.vn")],
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
    number: Annotated[str, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'")],
) -> None:
    """Crawl văn bản từ vbpl.vn -> data/raw/<raw_doc_code>/{source.txt,metadata.json}."""
    metadata = crawl_and_save(url, doc_id=raw_doc_code, number=number, raw_dir=settings.data_raw_dir)
    typer.echo(f"Đã crawl {raw_doc_code}: {metadata.title} ({metadata.status})")


# Lệnh CLI để cào hàng loạt văn bản pháp luật dựa trên từ khóa tìm kiếm trên vbpl.vn.
@app.command()
def crawl_search(
    query: Annotated[str, typer.Option(help="Từ khóa tìm kiếm trên vbpl.vn (vd: 'Luật Doanh nghiệp số')")],
    limit: Annotated[int, typer.Option(help="Số lượng văn bản tối đa muốn crawl")] = 10,
) -> None:
    """Crawl hàng loạt văn bản từ vbpl.vn dựa trên từ khóa tìm kiếm."""
    results = crawl_by_search(query, raw_dir=settings.data_raw_dir, limit=limit)
    typer.echo(f"Đã crawl thành công {len(results)} văn bản dựa trên tìm kiếm từ khóa '{query}'.")


# Lệnh CLI để phân tách cấu trúc văn bản pháp luật (Chương/Điều/Khoản/Điểm) từ file thô hoặc Text.
@app.command()
def parse(
    raw_doc_code: Annotated[
        str | None,
        typer.Option(help="Filesystem document code, vd 'L59_2020'. Nếu không truyền, parse curated folders trong data/raw/"),
    ] = None,
    txt: Annotated[
        Path | None,
        typer.Option(help="Parse trực tiếp từ file text (.txt) tự chọn."),
    ] = None,
) -> None:
    """Parse văn bản -> data/processed/<raw_doc_code>/hierarchy.json.

    Mặc định đọc data/raw/<raw_doc_code>/source.txt (output của `crawl`, lấy từ HTML body).
    Dùng `--txt <path>` để parse trực tiếp từ file text (.txt).
    Nếu không truyền --raw-doc-code và không dùng --txt, chỉ parse các thư mục thuộc curated manifest.
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
            parsed = parse_text(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        out_dir = settings.data_processed_dir / raw_doc_code
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed {raw_doc_code}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}")
        return

    # 2. Nếu không dùng --txt và truyền --raw-doc-code cụ thể để parse một thư mục
    if raw_doc_code is not None:
        raw_dir = _raw_dir(raw_doc_code)
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(f"Thiếu {source_path} hoặc {metadata_path} — chạy `crawl` trước (hoặc dùng --txt).", err=True)
            raise typer.Exit(code=1)

        try:
            doc_info = _document_info_from_metadata(_ready_metadata(raw_doc_code))
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        text = source_path.read_text(encoding="utf-8")
        try:
            parsed = parse_text(text, doc_info)
        except ValueError as exc:
            typer.echo(f"Parse validation error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        out_dir = _processed_dir(raw_doc_code)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed {raw_doc_code}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}")
        return

    # 3. Nếu không truyền --txt/--raw-doc-code, parse các thư mục curated trong data/raw/
    if not settings.data_raw_dir.exists():
        typer.echo(f"Thư mục nguồn {settings.data_raw_dir} không tồn tại.", err=True)
        raise typer.Exit(code=1)

    curated_codes = set(load_curated_manifest(settings.curated_manifest_path))
    subdirs = [p for p in settings.data_raw_dir.iterdir() if p.is_dir() and p.name in curated_codes]
    valid_folders = [p.name for p in subdirs if (p / "source.txt").exists() and (p / "metadata.json").exists()]

    if not valid_folders:
        typer.echo("Không tìm thấy thư mục hợp lệ nào chứa cả source.txt và metadata.json trong data/raw/.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Tìm thấy {len(valid_folders)} thư mục hợp lệ trong data/raw/. Bắt đầu parse song song...")
    
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

    typer.echo(f"Hoàn thành parse hàng loạt: Đã parse {parsed_count}/{len(valid_folders)} thư mục.")


# Lệnh CLI để trích xuất thực thể, quan hệ từ cấu trúc đã phân tách sử dụng mô hình LLM.
@app.command()
def extract(
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
    articles: Annotated[
        str | None,
        typer.Option(help="Comma-separated Article numbers for smoke extraction; omitted means full document."),
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

    parsed = ParsedDocument.model_validate_json(hierarchy_path.read_text(encoding="utf-8"))
    selected = {value.strip().lower() for value in articles.split(",") if value.strip()} if articles else None
    try:
        run_pipeline(
            parsed,
            settings.data_processed_dir,
            raw_doc_code=raw_doc_code,
            article_numbers=selected,
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
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
    articles: Annotated[
        str | None,
        typer.Option(help="Comma-separated checkpoint Article numbers; omitted means full document."),
    ] = None,
) -> None:
    """Regenerate decision artifacts from valid per-Article checkpoints without LLM calls."""
    hierarchy_path = _processed_dir(raw_doc_code) / "hierarchy.json"
    if not hierarchy_path.exists():
        typer.echo(f"Thiếu {hierarchy_path} — chạy `parse` trước.", err=True)
        raise typer.Exit(code=1)
    parsed = ParsedDocument.model_validate_json(hierarchy_path.read_text(encoding="utf-8"))
    selected = {value.strip().lower() for value in articles.split(",") if value.strip()} if articles else None
    try:
        run_pipeline(
            parsed,
            settings.data_processed_dir,
            raw_doc_code=raw_doc_code,
            provider_calls_allowed=False,
            article_numbers=selected,
        )
    except (ExtractionProviderError, ValueError) as exc:
        typer.echo(f"Extraction normalization blocked: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Decision artifacts regenerated from checkpoints for {raw_doc_code}")


@app.command("archive-extraction")
def archive_extraction(
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
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
    existing = [processed_dir / name for name in names if (processed_dir / name).exists()]
    if not existing:
        typer.echo(f"Không có extraction artifacts để archive tại {processed_dir}", err=True)
        raise typer.Exit(code=1)
    archive_dir.mkdir(parents=True, exist_ok=False)
    for source in existing:
        shutil.move(str(source), archive_dir / source.name)
    def _line_count(name: str) -> int:
        path = archive_dir / name
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.exists() else 0

    entity_path = archive_dir / "entity_index.json"
    entity_total = len(json.loads(entity_path.read_text(encoding="utf-8"))) if entity_path.exists() else 0
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
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
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
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
) -> None:
    """Build and validate a graph payload without opening a Neo4j connection."""
    processed_dir = _processed_dir(raw_doc_code)
    try:
        validate_extraction_readiness(processed_dir)
    except ExtractionReadinessError as exc:
        typer.echo(f"Extraction readiness error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        payload = build_payload_from_paths(processed_dir)
    except PayloadBuildError as exc:
        typer.echo(f"Payload build error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    node_counts = Counter(node.get("type") for node in payload.get("nodes", []))
    relation_counts = Counter(relation.get("type") for relation in payload.get("relations", []))
    
    consistency = validate_payload_consistency(payload)
    dangling_endpoint_count = sum(1 for err in consistency.errors if "dangling" in err.lower())
    
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
        "embedding_target_count": sum(
            node_counts.get(label, 0) for label in ("Article", "Clause")
        ),
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


@app.command("write")
def write_graph(raw_doc_code: Annotated[str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")]) -> None:
    """Build accepted graph payload and write it to Neo4j through the guarded writer."""
    payload = _validated_payload_for_raw_doc_code(raw_doc_code)
    session = create_neo4j_session()
    try:
        service = GraphIngestionService(writer=Neo4jWriter(session=session))
        validated_payload = service.ingest(payload)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    typer.echo(
        f"Wrote graph for {raw_doc_code}: "
        f"{len(validated_payload.nodes)} nodes, {len(validated_payload.relations)} relations"
    )


@app.command("embed")
def embed_graph(
    raw_doc_code: Annotated[str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")],
    batch_size: Annotated[int, typer.Option(min=1, help="Embedding batch size")] = 32,
) -> None:
    """Generate and write configured-dimension Article/Clause embeddings."""
    payload = _validated_payload_for_raw_doc_code(raw_doc_code)
    texts_by_node_id = embedding_texts_by_node_id(payload)
    graph_id = _graph_id(payload)
    content_hashes = {node_id: embedding_content_hash(text) for node_id, text in texts_by_node_id.items()}

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
        generator = EmbeddingGenerator()
        for start in range(0, len(stale_ids), batch_size):
            batch_ids = stale_ids[start : start + batch_size]
            vectors = generator.encode([texts_by_node_id[node_id] for node_id in batch_ids])
            writer.write_embeddings(
                dict(zip(batch_ids, vectors, strict=True)),
                graph_id=graph_id,
                content_hashes={node_id: content_hashes[node_id] for node_id in batch_ids},
                model=settings.embedding_model,
                provider=settings.embedding_provider,
                normalized=True,
            )
            typer.echo(f"Embedded {min(start + len(batch_ids), len(stale_ids))}/{len(stale_ids)} stale targets")
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    typer.echo(f"Embedding complete for {raw_doc_code}: updated={len(stale_ids)}, skipped={len(texts_by_node_id) - len(stale_ids)}")


@app.command("graph-quality")
def graph_quality(raw_doc_code: Annotated[str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")]) -> None:
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
    parsed = ParsedDocument.model_validate_json(hierarchy_path.read_text(encoding="utf-8"))

    session = create_neo4j_session()
    try:
        report = GraphQualityReporter(session=session).generate_for_document(graph_id=parsed.document.id)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    report["extraction_decisions"] = decision_stats_from_paths(_processed_dir(raw_doc_code))
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
    typer.echo(json.dumps({"uri": safe_uri, "constraints": report.constraints, "indexes": report.user_indexes}, indent=2))


@app.command("graph-snapshot")
def graph_snapshot(
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
    output: Annotated[str | None, typer.Option(help="Evidence file name under snapshots/")] = None,
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
    output_name = output or datetime.now(timezone.utc).strftime("snapshot_%Y%m%dT%H%M%SZ.json")
    try:
        path = write_snapshot(snapshot, settings.data_reports_dir / raw_doc_code / "snapshots", output_name)
    except ValueError as exc:
        typer.echo(f"Snapshot output error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wrote graph snapshot -> {path}")


@app.command("vector-smoke")
def vector_smoke(raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code")]) -> None:
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
def milestone_a_report(raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code")]) -> None:
    """Validate pilot evidence without promoting the four-document corpus gate."""
    try:
        report = generate_milestone_a_report(raw_doc_code, settings.data_reports_dir)
    except MilestoneAReportError as exc:
        typer.echo(f"Milestone A evidence error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    json_path, md_path = write_milestone_a_report(report, settings.data_reports_dir / raw_doc_code)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    typer.echo(f"Report JSON -> {json_path}")
    typer.echo(f"Report Markdown -> {md_path}")
    if not report["pilot_evidence_pass"]:
        raise typer.Exit(code=1)


def _validated_payload_for_raw_doc_code(raw_doc_code: str) -> dict:
    processed_dir = _processed_dir(raw_doc_code)
    try:
        validate_extraction_readiness(processed_dir)
    except ExtractionReadinessError as exc:
        typer.echo(f"Extraction readiness error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        payload = build_payload_from_paths(processed_dir)
    except PayloadBuildError as exc:
        typer.echo(f"Payload build error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    consistency = validate_payload_consistency(payload)
    if not consistency.valid:
        for error in consistency.errors:
            typer.echo(f"Payload consistency error: {error}", err=True)
        raise typer.Exit(code=1)
    try:
        validate_graph_payload(payload)
    except GraphValidationError as exc:
        for error in exc.errors:
            typer.echo(f"Ontology validation error: {error}", err=True)
        raise typer.Exit(code=1) from exc
    return payload


def _graph_id(payload: dict) -> str:
    for node in payload.get("nodes", []):
        if node.get("type") == "Document":
            return str(node["id"])
    raise typer.BadParameter("Payload has no Document node")


# Lệnh CLI để chạy toàn bộ luồng tích hợp: cào dữ liệu, phân tách cấu trúc và trích xuất tri thức.
@app.command()
def ingest(
    url: Annotated[str, typer.Option(help="URL trang chi tiết vbpl.vn")],
    raw_doc_code: Annotated[str, typer.Option(help="Filesystem document code, vd 'L59_2020'")],
    number: Annotated[str, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'")],
) -> None:
    """Full pipeline: crawl -> parse -> extract."""
    crawl(url, raw_doc_code, number)
    parse(raw_doc_code)
    extract(raw_doc_code)


if __name__ == "__main__":
    app()
