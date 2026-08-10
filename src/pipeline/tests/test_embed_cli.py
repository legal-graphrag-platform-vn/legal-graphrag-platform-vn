from __future__ import annotations


class _Session:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Writer:
    verified = False

    def __init__(self, *, session) -> None:
        self.session = session

    def verify_vector_indexes(self) -> None:
        type(self).verified = True

    def stale_target_ids(self, graph_id, content_hashes, **provenance):
        assert graph_id == "ldn_2020"
        assert set(content_hashes) == {"ldn_2020_art1", "ldn_2020_art1_cl1"}
        assert provenance["model"] == "BAAI/bge-m3"
        assert provenance["provider"] == "flag_embedding"
        assert provenance["normalized"] is True
        return ["ldn_2020_art1_cl1"]


def test_embed_dry_run_checks_readiness_without_loading_model_or_writing(
    monkeypatch, capsys
) -> None:
    import src.pipeline.main as main

    payload = {
        "nodes": [
            {"id": "ldn_2020", "type": "Document"},
            {
                "id": "ldn_2020_art1",
                "type": "Article",
                "number": "1",
                "title": "Phạm vi",
                "content_raw": "Nội dung điều.",
            },
            {
                "id": "ldn_2020_art1_cl1",
                "type": "Clause",
                "number": "1",
                "content_raw": "Nội dung khoản.",
            },
        ],
        "relations": [
            {
                "type": "CONTAINS",
                "head_id": "ldn_2020_art1",
                "tail_id": "ldn_2020_art1_cl1",
            }
        ],
    }
    session = _Session()
    _Writer.verified = False
    monkeypatch.setattr(main, "_validated_payload_for_raw_doc_code", lambda _: payload)
    monkeypatch.setattr(main, "create_neo4j_session", lambda: session)
    monkeypatch.setattr(main, "Neo4jEmbeddingWriter", _Writer)
    monkeypatch.setattr(
        main,
        "EmbeddingGenerator",
        lambda: (_ for _ in ()).throw(AssertionError("model must not load")),
    )

    main.embed_graph("L59_2020", batch_size=32, dry_run=True)

    output = capsys.readouterr().out
    assert _Writer.verified is True
    assert session.closed is True
    assert "targets=2" in output
    assert "stale=1" in output
    assert "current=1" in output
    assert "dimension=1024" in output
