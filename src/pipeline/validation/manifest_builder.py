"""Manifest builder cho LuatVietnam dataset và các nguồn dữ liệu thô.

Quét toàn bộ thư mục raw, trích xuất và chuẩn hóa metadata (doc_type, graph_id, number)
để tạo file manifest chuẩn phục vụ validation và batch processing.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from src.shared.ontology.contract import DOCUMENT_TYPES

logger = logging.getLogger(__name__)

GRAPH_ID_CLEAN_REGEX = re.compile(r"[^a-z0-9]+")


def _ascii_normalize(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và đưa về chữ thường."""
    # 1. Chuẩn hóa NFD để tách dấu tiếng Việt
    normalized = unicodedata.normalize("NFD", text)
    # 2. Lọc bỏ các ký tự dấu (Combining Diacritical Marks)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    # 3. Thay đ/Đ và chuyển chữ thường
    return normalized.replace("đ", "d").replace("Đ", "D").lower().strip()


def infer_doc_type_from_title(title: str) -> str:
    """Suy ra doc_type từ tiêu đề văn bản tiếng Việt."""
    # 1. Chuẩn hóa tiêu đề tiếng Việt không dấu
    norm_title = _ascii_normalize(title)

    # 2. Phân loại theo từ khóa tiêu đề
    if "hien phap" in norm_title:
        return "Constitution"
    elif "luat" in norm_title or "bo luat" in norm_title:
        return "Law"
    elif "phap lenh" in norm_title:
        return "Ordinance"
    elif "nghi quyet" in norm_title:
        return "Resolution"
    elif "nghi dinh" in norm_title:
        return "Decree"
    elif "thong tu lien tich" in norm_title:
        return "JointCircular"
    elif "thong tu" in norm_title:
        return "Circular"
    elif "quyet dinh" in norm_title:
        return "Decision"

    # Fallback mặc định cho văn bản không rõ
    return "Circular"


def sanitize_graph_id(raw_doc_code: str, number: str | None = None, title: str | None = None) -> str:
    """Tạo graph_id chuẩn khớp regex ^[a-z0-9]+(?:_[a-z0-9]+)*$."""
    # 1. Thử tạo từ number nếu có
    if number:
        norm_number = _ascii_normalize(number)
        cleaned = GRAPH_ID_CLEAN_REGEX.sub("_", norm_number).strip("_")
        if cleaned:
            return cleaned

    # 2. Thử tạo từ title nếu number rỗng
    if title:
        norm_title = _ascii_normalize(title)
        cleaned = GRAPH_ID_CLEAN_REGEX.sub("_", norm_title).strip("_")
        if cleaned:
            return cleaned[:40].strip("_")

    # 3. Fallback dùng raw_doc_code
    return raw_doc_code.lower()


def build_manifest_from_raw_dir(
    raw_dir: Path,
    *,
    required: bool = False,
    gold_annotation: bool = False,
) -> dict[str, Any]:
    """Quét toàn bộ thư mục raw_dir và trả về dictionary manifest hoàn chỉnh."""
    documents: list[dict[str, Any]] = []

    # 1. Lấy danh sách tất cả các thư mục con trong raw_dir
    doc_dirs = sorted([d for d in raw_dir.iterdir() if d.is_dir()])
    logger.info(f"Tìm thấy {len(doc_dirs)} thư mục văn bản trong {raw_dir}")

    # 2. Duyệt từng thư mục văn bản để trích xuất metadata
    for doc_dir in doc_dirs:
        raw_doc_code = doc_dir.name
        metadata_path = doc_dir / "metadata.json"

        if not metadata_path.exists():
            logger.warning(f"Bỏ qua {raw_doc_code}: không có metadata.json")
            continue

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            logger.error(f"Lỗi đọc metadata {metadata_path}: {exc}")
            continue

        # 3. Chuẩn hóa thông tin từng trường
        title = meta.get("title", "")
        number = meta.get("number") or ""
        
        # Đảm bảo doc_type thuộc DOCUMENT_TYPES
        doc_type = meta.get("doc_type") or meta.get("type")
        if not doc_type or doc_type not in DOCUMENT_TYPES:
            doc_type = infer_doc_type_from_title(title)

        # Đảm bảo graph_id hợp lệ
        graph_id = meta.get("graph_id") or meta.get("candidate_graph_id")
        if not graph_id or not re.match(r"^[a-z0-9]+(?:_[a-z0-9]+)*$", str(graph_id)):
            graph_id = sanitize_graph_id(raw_doc_code, number=number, title=title)

        documents.append({
            "raw_doc_code": raw_doc_code,
            "graph_id": str(graph_id),
            "number": str(number),
            "doc_type": doc_type,
            "required": required,
            "gold_annotation": gold_annotation,
        })

    # 4. Gom thành manifest hoàn chỉnh
    manifest_data = {
        "version": "1.0",
        "documents": documents,
    }
    return manifest_data


def generate_manifest_file(
    raw_dir: Path,
    output_manifest_path: Path,
    *,
    required: bool = False,
    gold_annotation: bool = False,
) -> int:
    """Tạo và ghi manifest JSON ra file đĩa."""
    # 1. Xây dựng nội dung manifest từ raw_dir
    manifest_data = build_manifest_from_raw_dir(
        raw_dir,
        required=required,
        gold_annotation=gold_annotation,
    )

    # 2. Tạo thư mục cha nếu chưa có
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # 3. Ghi ra file JSON
    with open(output_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    doc_count = len(manifest_data["documents"])
    logger.info(f"Đã xuất manifest thành công: {output_manifest_path} ({doc_count} văn bản)")
    return doc_count
