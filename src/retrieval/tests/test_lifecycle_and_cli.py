from pathlib import Path

import pytest

from src.retrieval import cli
from src.retrieval.cli import atomic_write_text
from src.retrieval.models import IntentType, RetrievalContext, TemporalQuery
from src.retrieval.runtime.lifecycle import RetrievalRuntimeHandle


class Runtime:
    pass


class FakeRuntimeHandle:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def retrieve(self, request):
        return RetrievalContext(
            query=request.query,
            intent=IntentType.FACTUAL,
            temporal=TemporalQuery(has_temporal=False),
            retrieved_units=[],
            graph_paths=[],
            evidence=[],
            metrics={},
            retrieval_mode="no_results",
            capability_status="no_results",
        )


def test_lifecycle_closes_owned_resources_once_in_reverse_order() -> None:
    events: list[str] = []
    handle = RetrievalRuntimeHandle(
        Runtime(),  # type: ignore[arg-type]
        close_callbacks=(
            lambda: events.append("first"),
            lambda: events.append("second"),
        ),
    )
    handle.close()
    handle.close()
    assert events == ["second", "first"]


def test_atomic_write_replaces_complete_output(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    output.write_text("old", encoding="utf-8")
    atomic_write_text(output, '{"status":"ok"}')
    assert output.read_text(encoding="utf-8") == '{"status":"ok"}'
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_cleans_temp_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "result.json"

    def fail_replace(self: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(Exception, match="Could not write retrieval output"):
        atomic_write_text(output, "payload")
    assert not list(tmp_path.glob("*.tmp"))


def test_cli_stdout_contains_version_and_forced_intent_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "create_retrieval_runtime", lambda: FakeRuntimeHandle())
    exit_code = cli.main(["retrieve", "--query", "quy định"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"contract_version": "retrieval-runtime-v2"' in captured.out
    assert '"force_intent_used": false' in captured.out
    assert captured.err == ""
