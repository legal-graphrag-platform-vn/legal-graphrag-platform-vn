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
    """Lưu dữ liệu cào từ LuatVietnam và tự động kết hợp VBPL lấy diagram.json & properties.json (nếu có)."""
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

    # 3. Thử cào bổ sung diagram.json & properties.json từ VBPL (nếu không có trên VBPL thì bỏ qua)
    diagram_path = saved_dir / "diagram.json"
    properties_path = saved_dir / "properties.json"

    if number and (not diagram_path.exists() or not properties_path.exists()):
        logger.info(f"Đang tìm kiếm số hiệu '{number}' trên VBPL để lấy bổ sung diagram/properties (nếu không tìm thấy sẽ bỏ qua)...")
        try:
            properties, diagram = fetch_vbpl_diagram_and_properties_by_number(number)
            
            if properties and not properties_path.exists():
                properties_path.write_text(json.dumps(properties, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"Đã bổ sung properties.json cho {raw_doc_code} từ VBPL")
                
            if diagram and not diagram_path.exists():
                diagram_path.write_text(json.dumps(diagram, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"Đã bổ sung diagram.json cho {raw_doc_code} từ VBPL")
        except Exception as exc:
            logger.warning(f"Không lấy được dữ liệu bổ sung từ VBPL cho số hiệu {number} (bỏ qua): {exc}")

    # 4. Tự động cập nhật manifest để văn bản mới sẵn sàng cho bước parse và extract
    try:
        from src.pipeline.validation.manifest_builder import generate_manifest_file

        generate_manifest_file(output_raw_dir, settings.curated_manifest_path)
        logger.info(f"Đã tự động cập nhật manifest cho {raw_doc_code}")
    except Exception as exc:
        logger.warning(f"Không thể tự động cập nhật manifest: {exc}")

    return saved_dir


def process_luatvietnam_html(
    html_text: str,
    source_url: str,
    output_raw_dir: Path = settings.luatvietnam_raw_dir,
) -> Path:
    """Parse HTML chi tiết từ LuatVietnam và lưu thành văn bản thô (kèm kết hợp VBPL)."""
    doc = parse_document(html_text, source_url=source_url)
    saved_dir = save_luatvietnam_raw(doc, output_raw_dir)
    return saved_dir


def infer_raw_doc_code_from_number(number: str | None, title: str | None = None) -> str:
    """Tự động sinh raw_doc_code chuẩn hóa cho 26 loại hình thức văn bản VBPL (vd 'L59_2020', 'ND01_2021', 'DT_...')."""
    import re
    import time
    import unicodedata

    target_text = f"{number or ''} {title or ''}".strip()
    norm_text = unicodedata.normalize("NFD", target_text)
    norm_text = "".join(c for c in norm_text if unicodedata.category(c) != "Mn")
    norm_upper = norm_text.upper().replace("Đ", "D")

    # Quy ước tiền tố mã hóa cho toàn bộ 26 hình thức văn bản CSDL Quốc gia VBPL:
    if "DU THAO" in norm_upper or "DRAFT" in norm_upper:
        prefix = "DT"
    elif "HIEN PHAP" in norm_upper or "CONSTITUTION" in norm_upper:
        prefix = "HP"
    elif "BO LUAT" in norm_upper:
        prefix = "BL"
    elif "LUAT" in norm_upper or "QH" in norm_upper:
        prefix = "L"
    elif "PHAP LENH" in norm_upper or "ORDINANCE" in norm_upper:
        prefix = "PL"
    elif "NGHI QUYET LIEN TICH" in norm_upper or "NQLT" in norm_upper:
        prefix = "NQLT"
    elif "NGHI QUYET" in norm_upper or "NQ" in norm_upper:
        prefix = "NQ"
    elif "NGHI DINH" in norm_upper or "ND-CP" in norm_upper or "ND" in norm_upper:
        prefix = "ND"
    elif "THONG TU LIEN TICH" in norm_upper or "TTLT" in norm_upper:
        prefix = "TTLT"
    elif "THONG TU" in norm_upper or "TT" in norm_upper:
        prefix = "TT"
    elif "QUYET DINH" in norm_upper or "QD" in norm_upper:
        prefix = "QD"
    elif "LENH" in norm_upper:
        prefix = "LENH"
    elif "CHI THI" in norm_upper or "CT" in norm_upper:
        prefix = "CT"
    elif "QUY CHE" in norm_upper or "QC" in norm_upper:
        prefix = "QC"
    elif "QUY DINH" in norm_upper or "QDINH" in norm_upper:
        prefix = "QDINH"
    elif "CONG VAN" in norm_upper or "CV" in norm_upper:
        prefix = "CV"
    elif "CONG DIEN" in norm_upper or "CD" in norm_upper:
        prefix = "CD"
    elif "TO TRINH" in norm_upper or "TTR" in norm_upper:
        prefix = "TTR"
    elif "THONG BAO" in norm_upper or "TB" in norm_upper:
        prefix = "TB"
    elif "HUONG DAN" in norm_upper or "HD" in norm_upper:
        prefix = "HD"
    elif "VAN BAN HOP NHAT" in norm_upper or "VBHN" in norm_upper:
        prefix = "VBHN"
    elif "HE THONG HOA" in norm_upper or "HTH" in norm_upper:
        prefix = "HTH"
    elif "HANH CHINH LIEN QUAN" in norm_upper or "HCKL" in norm_upper:
        prefix = "HCKL"
    elif "BAN DICH" in norm_upper or "TRANSLATION" in norm_upper:
        prefix = "BD"
    elif "KE HOACH" in norm_upper or "KH" in norm_upper:
        prefix = "KH"
    elif "BAO CAO" in norm_upper or "BIEN BAN" in norm_upper or "BC" in norm_upper:
        prefix = "BC"
    else:
        prefix = "DOC"

    if not number or not number.strip():
        if title:
            slug = re.sub(r"[^a-z0-9]+", "_", norm_text.lower()).strip("_")[:30]
            if slug:
                return f"{prefix}_{slug}_{int(time.time())}"
        return f"{prefix}_{int(time.time())}"

    num_match = re.search(r"(\d+)(?:/(\d{4}))?", number)
    num_part = num_match.group(1) if num_match else "0"
    year_part = num_match.group(2) if num_match and num_match.group(2) else "unknown"

    return f"{prefix}{num_part}_{year_part}"


def crawl_luatvietnam_url(
    url: str,
    raw_doc_code: str | None = None,
    number: str | None = None,
    output_raw_dir: Path = settings.data_raw_dir,
    timeout_ms: int = 30000,
) -> Path:
    """Crawl trực tiếp từ URL LuatVietnam -> save source.txt & metadata.json -> bổ sung VBPL diagram/properties nếu có."""
    from playwright.sync_api import sync_playwright

    logger.info("Bắt đầu crawl từ LuatVietnam URL: %s", url)
    html_text = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        html_text = page.content()
        browser.close()

    from dataclasses import replace

    doc = parse_document(html_text, source_url=url)
    
    # Nếu người dùng không truyền raw_doc_code, tự động sinh từ số hiệu hoặc tiêu đề
    if not raw_doc_code:
        doc_number = number or doc.number
        doc_title = getattr(doc, "title", None)
        raw_doc_code = infer_raw_doc_code_from_number(doc_number, title=doc_title)
        logger.info("Tự động sinh raw_doc_code: %s (từ số hiệu: '%s')", raw_doc_code, doc_number)

    doc = replace(doc, raw_doc_code=raw_doc_code)

    saved_dir = save_luatvietnam_raw(doc, output_raw_dir)
    return saved_dir
