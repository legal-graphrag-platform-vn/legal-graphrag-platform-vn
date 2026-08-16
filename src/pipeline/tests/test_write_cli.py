from __future__ import annotations

import json
from datetime import date

from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument


def test_validated_payload_helper_uses_raw_doc_code_directory(tmp_path, monkeypatch) -> None:
    import src.pipeline.main as main

    raw_doc_code = "LDN2020"
    processed_dir = tmp_path / raw_doc_code
    processed_dir.mkdir()
    monkeypatch.setattr(main.settings, "data_processed_dir", tmp_path)

    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            normative=True,
            legal_status="ACTIVE",
            effective_from=date(2021, 1, 1),
            issuer_name="Quốc hội",
        ),
        articles=[Article(number=17, title="Quyền", content_raw="Nội dung điều 17")],
    )
    (processed_dir / "hierarchy.json").write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
    accepted_record = {
        "decision": "accepted",
        "relation": {
            "head": "ldn_2020_art17",
            "relation": "DEFINES",
                "tail": "von_dieu_le",
            "properties": {
                "confidence": 0.9,
                "llm_model": "gemini:gemini-2.5-flash",
                "created_at": "2026-07-10T00:00:00Z",
            },
        },
    }
    (processed_dir / "accepted.jsonl").write_text(json.dumps(accepted_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (processed_dir / "extract.jsonl").write_text(json.dumps(accepted_record, ensure_ascii=False) + "\n", encoding="utf-8")
    (processed_dir / "review.jsonl").write_text("", encoding="utf-8")
    (processed_dir / "rejected.jsonl").write_text("", encoding="utf-8")
    (processed_dir / "entity_index.json").write_text(
        json.dumps(
            {
                    "von_dieu_le": {
                    "id": "von_dieu_le",
                    "type": "LegalConcept",
                    "label": "Vốn điều lệ",
                    "name": "Vốn điều lệ",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = main._validated_payload_for_raw_doc_code(raw_doc_code)

    assert any(node["id"] == "ldn_2020" for node in payload["nodes"])
    assert any(relation["type"] == "DEFINES" for relation in payload["relations"])


def test_validated_payload_helper_structural_mode_without_extraction_artifacts(tmp_path, monkeypatch) -> None:
    import src.pipeline.main as main

    raw_doc_code = "LDN2020_STRUCTURAL"
    processed_dir = tmp_path / raw_doc_code
    processed_dir.mkdir()
    monkeypatch.setattr(main.settings, "data_processed_dir", tmp_path)

    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            normative=True,
            legal_status="ACTIVE",
            effective_from=date(2021, 1, 1),
            issuer_name="Quốc hội",
        ),
        articles=[Article(number=17, title="Quyền", content_raw="Nội dung điều 17")],
    )
    (processed_dir / "hierarchy.json").write_text(parsed.model_dump_json(indent=2), encoding="utf-8")

    # Call with mode="structural" when no accepted.jsonl / entity_index.json exists
    payload = main._validated_payload_for_raw_doc_code(raw_doc_code, mode="structural")

    assert any(node["id"] == "ldn_2020" for node in payload["nodes"])
    assert any(node["id"] == "ldn_2020_art17" for node in payload["nodes"])
    assert any(relation["type"] == "CONTAINS" for relation in payload["relations"])
    assert not any(relation["type"] == "DEFINES" for relation in payload["relations"])


def test_discover_processed_doc_codes(tmp_path) -> None:
    import src.pipeline.main as main

    # doc1: has hierarchy.json
    doc1 = tmp_path / "DOC1"
    doc1.mkdir()
    (doc1 / "hierarchy.json").write_text("{}", encoding="utf-8")

    # doc2: has hierarchy.json
    doc2 = tmp_path / "DOC2"
    doc2.mkdir()
    (doc2 / "hierarchy.json").write_text("{}", encoding="utf-8")

    # doc3: does NOT have hierarchy.json
    doc3 = tmp_path / "DOC3"
    doc3.mkdir()

    codes = main._discover_processed_doc_codes(tmp_path)
    assert codes == ["DOC1", "DOC2"]

    # Test limit
    limited = main._discover_processed_doc_codes(tmp_path, limit=1)
    assert limited == ["DOC1"]


def test_batch_write_structural_invokes_write_graph(tmp_path, monkeypatch) -> None:
    import src.pipeline.main as main

    doc1 = tmp_path / "DOC1"
    doc1.mkdir()
    (doc1 / "hierarchy.json").write_text("{}", encoding="utf-8")

    written = []

    def mock_write_graph(code: str, mode: str = "full"):
        written.append((code, mode))

    monkeypatch.setattr(main, "write_graph", mock_write_graph)

    main.batch_write(processed_dir=tmp_path, mode="structural")
    assert written == [("DOC1", "structural")]


def test_discover_extraction_ready_doc_codes(tmp_path) -> None:
    import src.pipeline.main as main

    # doc1: has accepted.jsonl + entity_index.json
    doc1 = tmp_path / "DOC1"
    doc1.mkdir()
    (doc1 / "accepted.jsonl").write_text("{}", encoding="utf-8")
    (doc1 / "entity_index.json").write_text("{}", encoding="utf-8")

    # doc2: only has hierarchy.json (not extraction ready)
    doc2 = tmp_path / "DOC2"
    doc2.mkdir()
    (doc2 / "hierarchy.json").write_text("{}", encoding="utf-8")

    codes = main._discover_extraction_ready_doc_codes(tmp_path)
    assert codes == ["DOC1"]


def test_batch_sync_semantics_invokes_write_graph_full(tmp_path, monkeypatch) -> None:
    import src.pipeline.main as main

    doc1 = tmp_path / "DOC1"
    doc1.mkdir()
    (doc1 / "accepted.jsonl").write_text("{}", encoding="utf-8")
    (doc1 / "entity_index.json").write_text("{}", encoding="utf-8")

    synced = []

    def mock_write_graph(code: str, mode: str = "full"):
        synced.append((code, mode))

    monkeypatch.setattr(main, "write_graph", mock_write_graph)

    main.batch_sync_semantics(processed_dir=tmp_path)
    assert synced == [("DOC1", "full")]



