from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.pipeline.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_default_data_paths_use_repo_root(monkeypatch) -> None:
    for name in (
        "DATA_RAW_DIR",
        "DATA_PROCESSED_DIR",
        "DATA_REPORTS_DIR",
        "CURATED_MANIFEST_PATH",
        "EMBEDDING_MODEL",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_DIM",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.data_raw_dir == REPO_ROOT / "data" / "raw"
    assert settings.data_processed_dir == REPO_ROOT / "data" / "processed"
    assert settings.data_reports_dir == REPO_ROOT / "data" / "reports"
    assert settings.curated_manifest_path == REPO_ROOT / "configs" / "corpus" / "curated_v1.json"
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.embedding_provider == "flag_embedding"
    assert settings.embedding_dimension == 1024


def test_module_cli_entrypoint_runs_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.pipeline.main", "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Graph Construction Pipeline" in result.stdout


def test_parse_cli_uses_raw_doc_code_option() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.pipeline.main", "parse", "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--raw-doc-code" in result.stdout
    assert "--doc-id" not in result.stdout


def test_schema_embedding_dimension_matches_settings(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    settings = Settings(_env_file=None)
    schema = (REPO_ROOT / "infra" / "neo4j" / "init" / "01_schema_init.cypher").read_text(encoding="utf-8")

    dimension_contract = f"`vector.dimensions`: {settings.embedding_dimension}"
    assert schema.count(dimension_contract) == 2
