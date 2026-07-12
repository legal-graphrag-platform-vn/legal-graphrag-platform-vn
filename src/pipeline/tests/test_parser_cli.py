from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

from src.pipeline.main import app
from src.pipeline.config import settings

runner = CliRunner()


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "curated.json"
    path.write_text(json.dumps({"version": "test", "documents": entries}), encoding="utf-8")
    return path


def test_parse_cli_single_folder(tmp_path: Path) -> None:
    # 1.   Prepare raw data folder structure in mock temp directory
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    
    raw_doc_code = "L59_2020"
    doc_raw_dir = raw_dir / raw_doc_code
    doc_raw_dir.mkdir(parents=True, exist_ok=True)
    
    # 2.   Write sample source.txt and metadata.json
    (doc_raw_dir / "source.txt").write_text("Điều 1. Phạm vi điều chỉnh\nLuật này quy định...", encoding="utf-8")
    metadata = {
        "doc_id": raw_doc_code,
        "graph_id": "ldn_2020",
        "title": "Luật Doanh nghiệp 2020",
        "number": "59/2020/QH14",
        "type": "Law",
        "issuer_name": "Quốc hội",
        "status": "active",
        "effective_from": "2021-01-01",
        "source_url": "https://vbpl.vn/test",
    }
    (doc_raw_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path,
        [{"raw_doc_code": raw_doc_code, "graph_id": "ldn_2020", "number": "59/2020/QH14", "doc_type": "Law"}],
    )

    # 3.   Execute parse command pointing to the mock directories
    with patch.object(settings, "data_raw_dir", raw_dir), \
         patch.object(settings, "data_processed_dir", processed_dir), \
         patch.object(settings, "curated_manifest_path", manifest_path):
         
        result = runner.invoke(app, ["parse", "--raw-doc-code", raw_doc_code])
        
        # 4.   Verify output log and processed file creation
        assert result.exit_code == 0
        assert f"Parsed {raw_doc_code}" in result.stdout
        
        processed_file = processed_dir / raw_doc_code / "hierarchy.json"
        assert processed_file.exists()
        
        parsed_data = json.loads(processed_file.read_text(encoding="utf-8"))
        assert parsed_data["document"]["id"] == "ldn_2020"
        assert parsed_data["document"]["doc_type"] == "Law"
        assert parsed_data["document"]["normative"] is True
        assert parsed_data["document"]["issuer_name"] == "Quốc hội"
        assert parsed_data["document"]["legal_status"] == "ACTIVE"
        assert "status" not in parsed_data["document"]
        assert len(parsed_data["articles"]) == 1
        assert parsed_data["articles"][0]["number"] == "1"


def test_parse_cli_bulk_folders(tmp_path: Path) -> None:
    # 1.   Prepare multiple raw folders in temp directory
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    
    folders = ["L59_2020", "ND258_2026"]
    manifest_entries = []
    for raw_doc_code in folders:
        doc_raw_dir = raw_dir / raw_doc_code
        doc_raw_dir.mkdir(parents=True, exist_ok=True)
        (doc_raw_dir / "source.txt").write_text(f"Điều 1. Phạm vi của {raw_doc_code}", encoding="utf-8")
        metadata = {
            "doc_id": raw_doc_code,
            "title": f"Document {raw_doc_code}",
            "number": f"123/{raw_doc_code}",
            "doc_type": "Law",
            "status": "active",
            "effective_from": "2021-01-01",
            "issued_by": "Quốc hội",
            "source_url": "https://vbpl.vn/test",
        }
        (doc_raw_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        manifest_entries.append(
            {
                "raw_doc_code": raw_doc_code,
                "graph_id": raw_doc_code.lower(),
                "number": metadata["number"],
                "doc_type": "Law",
            }
        )
    manifest_path = _write_manifest(tmp_path, manifest_entries)
        
    # 2.   Execute parse command without specifying doc-id (bulk mode)
    with patch.object(settings, "data_raw_dir", raw_dir), \
         patch.object(settings, "data_processed_dir", processed_dir), \
         patch.object(settings, "curated_manifest_path", manifest_path):
         
        result = runner.invoke(app, ["parse"])
        
        # 3.   Verify bulk execution output logs
        assert result.exit_code == 0
        assert "Tìm thấy 2 thư mục hợp lệ" in result.stdout
        assert "Parsed thành công L59_2020" in result.stdout
        assert "Parsed thành công ND258_2026" in result.stdout
        assert "Hoàn thành parse hàng loạt: Đã parse 2/2" in result.stdout
        
        # 4.   Verify all folders were processed
        for raw_doc_code in folders:
            assert (processed_dir / raw_doc_code / "hierarchy.json").exists()
