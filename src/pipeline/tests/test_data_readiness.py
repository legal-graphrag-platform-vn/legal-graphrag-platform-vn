from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.validation.data_readiness import validate_document_readiness


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "curated.json"
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "documents": [
                    {
                        "raw_doc_code": "L59_2020",
                        "graph_id": "ldn_2020",
                        "number": "59/2020/QH14",
                        "doc_type": "Law",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_readiness_normalizes_raw_code_to_canonical_graph_id(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    document_dir = raw_root / "L59_2020"
    document_dir.mkdir(parents=True)
    (document_dir / "source.txt").write_text("Điều 1. Phạm vi điều chỉnh", encoding="utf-8")
    (document_dir / "metadata.json").write_text(
        json.dumps(
            {
                "doc_id": "L59_2020",
                "title": "Luật Doanh nghiệp 2020",
                "number": "59/2020/QH14",
                "doc_type": "Law",
                "issued_by": "QUỐC HỘI",
                "effective_from": "2021-01-01",
                "status": "Hết hiệu lực một phần",
                "source_url": "https://vbpl.vn/test",
            }
        ),
        encoding="utf-8",
    )

    result = validate_document_readiness(
        "L59_2020",
        raw_root,
        manifest_path=_manifest(tmp_path),
    )

    assert result.valid, result.errors
    assert result.normalized_metadata["raw_doc_code"] == "L59_2020"
    assert result.normalized_metadata["graph_id"] == "ldn_2020"
    assert result.normalized_metadata["normative"] is True
    assert result.normalized_metadata["legal_status"] == "PARTIALLY_EFFECTIVE"
    assert result.normalized_metadata["issuer_name"] == "QUỐC HỘI"
    assert result.normalized_metadata["issuer_branch"] == "LEGISLATIVE"


def test_readiness_rejects_document_outside_curated_manifest(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    document_dir = raw_root / "UNKNOWN"
    document_dir.mkdir(parents=True)
    (document_dir / "source.txt").write_text("text", encoding="utf-8")
    (document_dir / "metadata.json").write_text("{}", encoding="utf-8")

    result = validate_document_readiness(
        "UNKNOWN",
        raw_root,
        manifest_path=_manifest(tmp_path),
    )

    assert not result.valid
    assert "curated manifest" in result.errors[0]


def test_readiness_rejects_unknown_status_instead_of_defaulting_active(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    document_dir = raw_root / "L59_2020"
    document_dir.mkdir(parents=True)
    (document_dir / "source.txt").write_text("text", encoding="utf-8")
    (document_dir / "metadata.json").write_text(
        json.dumps({"doc_id": "L59_2020", "status": "khong ro", "number": "59/2020/QH14", "doc_type": "Law"}),
        encoding="utf-8",
    )

    result = validate_document_readiness("L59_2020", raw_root, manifest_path=_manifest(tmp_path))

    assert not result.valid
    assert any("refusing to default to ACTIVE" in error for error in result.errors)


def test_readiness_rejects_manifest_identity_mismatch(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    document_dir = raw_root / "L59_2020"
    document_dir.mkdir(parents=True)
    (document_dir / "source.txt").write_text("text", encoding="utf-8")
    (document_dir / "metadata.json").write_text(
        json.dumps({"doc_id": "L59_2020", "status": "active", "number": "WRONG", "doc_type": "Law"}),
        encoding="utf-8",
    )

    result = validate_document_readiness("L59_2020", raw_root, manifest_path=_manifest(tmp_path))

    assert not result.valid
    assert any("Metadata mismatch for number" in error for error in result.errors)
