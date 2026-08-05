"""Module crawler tương thích cho luatvietnam.vn tích hợp vào pipeline.

Cho phép cào trực tiếp văn bản từ luatvietnam.vn và lưu về đúng cấu trúc raw_dir
bao gồm source.txt, metadata.json, source.html.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.pipeline.config import settings
from experiments.luatvietnam_crawler.parser import parse_document
from experiments.luatvietnam_crawler.storage import save_document

from src.pipeline.crawler.vbpl_crawler import fetch_vbpl_diagram_and_properties_by_number

logger = logging.getLogger(__name__)


def save_luatvietnam_raw(
    doc_data: Any,
    output_raw_dir: Path,
) -> Path:
    """Lưu dữ liệu cào từ LuatVietnam và tự động kết hợp VBPL lấy diagram.json & properties.json."""
    # 1. Gọi storage saver của luatvietnam crawler
    saved_dir = save_document(doc_data, output_root=output_raw_dir)
    raw_doc_code = saved_dir.name
    logger.info(f"Đã lưu văn bản LuatVietnam vào: {saved_dir} (mã: {raw_doc_code})")

    # 2. Đọc metadata để lấy số hiệu văn bản
    metadata_path = saved_dir / "metadata.json"
    number = ""
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                number = meta.get("number") or ""
        except Exception as exc:
            logger.warning("Không thể đọc metadata để bổ sung VBPL: %s", exc)

    # 3. Mặc định kiểm tra và tự động cào bổ sung diagram.json & properties.json từ VBPL
    diagram_path = saved_dir / "diagram.json"
    properties_path = saved_dir / "properties.json"

    if number and (not diagram_path.exists() or not properties_path.exists()):
        logger.info(f"Mặc định kết hợp VBPL: Đang tìm kiếm số hiệu '{number}' để lấy diagram và properties...")
        properties, diagram = fetch_vbpl_diagram_and_properties_by_number(number)
        
        if properties and not properties_path.exists():
            properties_path.write_text(json.dumps(properties, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"Đã bổ sung properties.json cho {raw_doc_code} từ VBPL")
            
        if diagram and not diagram_path.exists():
            diagram_path.write_text(json.dumps(diagram, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"Đã bổ sung diagram.json cho {raw_doc_code} từ VBPL")

    return saved_dir


def process_luatvietnam_html(
    html_text: str,
    source_url: str,
    output_raw_dir: Path = settings.luatvietnam_raw_dir,
) -> Path:
    """Parse HTML chi tiết từ LuatVietnam và lưu thành văn bản thô (kèm kết hợp VBPL)."""
    # 1. Parse HTML bằng parser chuyên dụng LuatVietnam
    doc = parse_document(html_text, source_url=source_url)

    # 2. Lưu vào thư mục raw_dir và kết hợp cào diagram/properties từ VBPL
    saved_dir = save_luatvietnam_raw(doc, output_raw_dir)
    return saved_dir
