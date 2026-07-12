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
