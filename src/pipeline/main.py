"""CLI entrypoint cho Graph Construction Pipeline (Milestone 1+2).

    python main.py crawl --url <vbpl_url> --doc-id LDN2020 --number 59/2020/QH14
    python main.py parse --doc-id LDN2020
    python main.py extract --doc-id LDN2020
    python main.py ingest --url <vbpl_url> --doc-id LDN2020 --number 59/2020/QH14

`extract` cần GEMINI_API_KEY trong .env (xem .env.example và README).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from src.config import settings
from src.crawler.vbpl_crawler import crawl_and_save, crawl_by_search
from src.embedding.embedding_generator import EmbeddingGenerator, embedding_texts_by_node_id
from src.embedding.neo4j_embedding_writer import Neo4jEmbeddingWriter
from src.parser.hierarchy_parser import parse_text
from src.parser.models import DocumentInfo, ParsedDocument
from src.persistence.neo4j_writer import GraphIngestionService, Neo4jWriter, create_neo4j_session, validate_graph_payload
from src.persistence.payload_builder import build_payload_from_paths
from src.pipeline.orchestrator import run_pipeline
from src.reports.graph_quality import GraphQualityReporter, write_graph_quality_report
from src.validation.payload_consistency_validator import validate_payload_consistency

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer(help="Legal GraphRAG — Graph Construction Pipeline (Milestone 1+2)")


def _legal_status_from_raw(raw_status: str | None) -> str:
    normalized = (raw_status or "active").strip().lower()
    if normalized in {"active", "còn hiệu lực", "con hieu luc"}:
        return "ACTIVE"
    if normalized in {"chưa có hiệu lực", "chua co hieu luc"}:
        return "NOT_YET_EFFECTIVE"
    if normalized in {"hết hiệu lực một phần", "het hieu luc mot phan"}:
        return "PARTIALLY_EFFECTIVE"
    if normalized in {"hết hiệu lực toàn bộ", "het hieu luc toan bo"}:
        return "EXPIRED"
    return "ACTIVE"


def _document_info_from_metadata(meta: dict, fallback_id: str | None = None) -> DocumentInfo:
    return DocumentInfo(
        id=meta.get("graph_id") or meta.get("doc_id") or fallback_id,
        title=meta["title"],
        number=meta["number"],
        doc_type=meta.get("doc_type") or meta.get("type"),
        normative=meta.get("normative", True),
        issued_by=meta.get("issued_by"),
        issuer_name=meta.get("issuer_name") or meta.get("issued_by"),
        issued_date=meta.get("issued_date"),
        effective_from=meta.get("effective_from"),
        effective_to=meta.get("effective_to"),
        legal_status=meta.get("legal_status") or _legal_status_from_raw(meta.get("status")),
    )


# Lấy đường dẫn thư mục lưu trữ dữ liệu thô (raw data) của văn bản.
def _raw_dir(doc_id: str) -> Path:
    return settings.data_raw_dir / doc_id


# Lấy đường dẫn thư mục lưu trữ dữ liệu đã xử lý (processed data) của văn bản.
def _processed_dir(doc_id: str) -> Path:
    return settings.data_processed_dir / doc_id


def _parse_folder_worker(folder_name: str) -> bool:
    """Worker xử lý parse cho 1 thư mục đơn lẻ."""
    try:
        raw_dir = settings.data_raw_dir / folder_name
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(f"Thư mục {folder_name} thiếu source.txt hoặc metadata.json", err=True)
            return False

        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        doc_info = _document_info_from_metadata(meta, fallback_id=folder_name)

        text = source_path.read_text(encoding="utf-8")
        parsed = parse_text(text, doc_info)

        out_dir = settings.data_processed_dir / folder_name
        out_dir.mkdir(parents=True, exist_ok=True)
        # Ghi đè file hierarchy.json nếu đã tồn tại
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed thành công {folder_name} -> {out_dir / 'hierarchy.json'}")
        return True
    except Exception as e:
        typer.echo(f"Lỗi khi parse thư mục {folder_name}: {e}", err=True)
        return False


# Lệnh CLI để cào thông tin chi tiết và nội dung văn bản pháp luật từ trang vbpl.vn.
@app.command()
def crawl(
    url: Annotated[str, typer.Option(help="URL trang chi tiết vbpl.vn")],
    doc_id: Annotated[str, typer.Option(help="Document ID, vd 'LDN2020'")],
    number: Annotated[str, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'")],
) -> None:
    """Crawl văn bản từ vbpl.vn -> data/raw/<doc_id>/{source.txt,metadata.json}."""
    metadata = crawl_and_save(url, doc_id=doc_id, number=number, raw_dir=settings.data_raw_dir)
    typer.echo(f"Đã crawl {doc_id}: {metadata.title} ({metadata.status})")


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
    doc_id: Annotated[
        str | None,
        typer.Option(help="Document ID, vd 'LDN2020'. Nếu không truyền, mặc định parse toàn bộ thư mục trong data/raw/"),
    ] = None,
    txt: Annotated[
        Path | None,
        typer.Option(help="Parse trực tiếp từ file text (.txt) tự chọn."),
    ] = None,
    number: Annotated[
        str | None, typer.Option(help="Số hiệu văn bản (chỉ cần khi dùng --txt mà chưa có metadata.json)")
    ] = None,
    title: Annotated[
        str | None, typer.Option(help="Tiêu đề văn bản (chỉ cần khi dùng --txt mà chưa có metadata.json)")
    ] = None,
) -> None:
    """Parse văn bản -> data/processed/<doc_id>/hierarchy.json.

    Mặc định đọc data/raw/<doc_id>/source.txt (output của `crawl`, lấy từ HTML body).
    Dùng `--txt <path>` để parse trực tiếp từ file text (.txt).
    Nếu không truyền --doc-id và không dùng --txt, sẽ parse tất cả thư mục trong data/raw.
    """
    # 1.   Nếu dùng --txt để parse trực tiếp từ file text tự chọn
    if txt is not None:
        if not txt.exists():
            typer.echo(f"File text không tồn tại: {txt}", err=True)
            raise typer.Exit(code=1)
        if not doc_id:
            typer.echo("Khi dùng --txt, bắt buộc phải truyền --doc-id để xác định định danh văn bản.", err=True)
            raise typer.Exit(code=1)

        metadata_path = settings.data_raw_dir / doc_id / "metadata.json"
        if metadata_path.exists():
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            doc_info = _document_info_from_metadata(meta, fallback_id=doc_id)
        else:
            if not number:
                typer.echo(
                    "Không có metadata.json — cần truyền --number (và tuỳ chọn --title) khi dùng --txt.",
                    err=True,
                )
                raise typer.Exit(code=1)
            doc_info = DocumentInfo(
                id=doc_id,
                title=title or doc_id,
                number=number,
                doc_type="Law",
                normative=True,
                legal_status="ACTIVE",
            )

        text = txt.read_text(encoding="utf-8")
        parsed = parse_text(text, doc_info)
        out_dir = settings.data_processed_dir / doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed {doc_id}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}")
        return

    # 2.   Nếu không dùng --txt và truyền --doc-id cụ thể để parse một thư mục
    if doc_id is not None:
        raw_dir = _raw_dir(doc_id)
        metadata_path = raw_dir / "metadata.json"
        source_path = raw_dir / "source.txt"

        if not source_path.exists() or not metadata_path.exists():
            typer.echo(f"Thiếu {source_path} hoặc {metadata_path} — chạy `crawl` trước (hoặc dùng --txt).", err=True)
            raise typer.Exit(code=1)

        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        doc_info = _document_info_from_metadata(meta, fallback_id=doc_id)

        text = source_path.read_text(encoding="utf-8")
        parsed = parse_text(text, doc_info)
        out_dir = _processed_dir(doc_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "hierarchy.json").write_text(
            parsed.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        typer.echo(f"Parsed {doc_id}: {len(parsed.articles)} Điều -> {out_dir / 'hierarchy.json'}")
        return

    # 3.   Nếu không truyền cả --txt và --doc-id, tự động quét và parse tất cả thư mục trong data/raw/
    if not settings.data_raw_dir.exists():
        typer.echo(f"Thư mục nguồn {settings.data_raw_dir} không tồn tại.", err=True)
        raise typer.Exit(code=1)

    subdirs = [p for p in settings.data_raw_dir.iterdir() if p.is_dir()]
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
def extract(doc_id: Annotated[str, typer.Option(help="Document ID, vd 'LDN2020'")]) -> None:
    """Chạy LLM Extraction + Validation + Scoring trên hierarchy.json đã parse."""
    try:
        settings.require_api_key()
    except Exception as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    hierarchy_path = _processed_dir(doc_id) / "hierarchy.json"
    if not hierarchy_path.exists():
        typer.echo(f"Thiếu {hierarchy_path} — chạy `parse` trước.", err=True)
        raise typer.Exit(code=1)

    parsed = ParsedDocument.model_validate_json(hierarchy_path.read_text(encoding="utf-8"))
    run_pipeline(parsed, settings.data_processed_dir, raw_doc_code=doc_id)
    typer.echo(
        f"Extraction xong cho {doc_id}: xem data/processed/{doc_id}/"
        "{extract.jsonl, accepted.jsonl, review.jsonl, rejected.jsonl, entity_index.json}"
    )


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
def embed_graph(raw_doc_code: Annotated[str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")]) -> None:
    """Generate and write 768-dim Article/Clause embeddings as a post-write step."""
    payload = _validated_payload_for_raw_doc_code(raw_doc_code)
    texts_by_node_id = embedding_texts_by_node_id(payload)
    node_ids = list(texts_by_node_id)
    texts = list(texts_by_node_id.values())
    vectors = EmbeddingGenerator().encode(texts)
    graph_id = _graph_id(payload)
    vectors_by_node_id = {node_id: vector for node_id, vector in zip(node_ids, vectors, strict=True)}

    session = create_neo4j_session()
    try:
        writer = Neo4jEmbeddingWriter(session=session)
        writer.verify_vector_indexes()
        writer.write_embeddings(vectors_by_node_id, graph_id=graph_id)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    typer.echo(f"Wrote {len(vectors_by_node_id)} embeddings for {raw_doc_code}")


@app.command("graph-quality")
def graph_quality(raw_doc_code: Annotated[str, typer.Option(help="Folder name under data/processed, vd 'LDN2020'")]) -> None:
    """Generate graph quality metrics from the canonical graph payload."""
    hierarchy_path = _processed_dir(raw_doc_code) / "hierarchy.json"
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
    out_dir = settings.data_reports_dir / raw_doc_code
    write_graph_quality_report(report, out_dir)
    typer.echo(f"Wrote graph quality report -> {out_dir}")


def _validated_payload_for_raw_doc_code(raw_doc_code: str) -> dict:
    payload = build_payload_from_paths(_processed_dir(raw_doc_code))
    consistency = validate_payload_consistency(payload)
    if not consistency.valid:
        for error in consistency.errors:
            typer.echo(f"Payload consistency error: {error}", err=True)
        raise typer.Exit(code=1)
    validate_graph_payload(payload)
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
    doc_id: Annotated[str, typer.Option(help="Document ID, vd 'LDN2020'")],
    number: Annotated[str, typer.Option(help="Số hiệu văn bản, vd '59/2020/QH14'")],
) -> None:
    """Full pipeline: crawl -> parse -> extract."""
    crawl(url, doc_id, number)
    parse(doc_id)
    extract(doc_id)


if __name__ == "__main__":
    app()
