from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]


def test_routes_do_not_import_retrieval_or_neo4j_concretes() -> None:
    forbidden = ("neo4j", "src.infrastructure", "src.retrieval.retriever")
    for path in (BACKEND_ROOT / "api" / "routes").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (
            f"{path} imports a concrete retrieval dependency: {imports}"
        )


def test_backend_service_does_not_import_channel_implementations() -> None:
    for path in (BACKEND_ROOT / "services").glob("*.py"):
        imports = _imports(path)
        assert not any(
            name.startswith("src.retrieval.retriever") for name in imports
        ), f"{path} imports channel implementation: {imports}"


def test_backend_container_is_only_backend_retrieval_composition_path() -> None:
    matches: list[Path] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if "create_retrieval_runtime" in path.read_text(encoding="utf-8"):
            matches.append(path.relative_to(REPO_ROOT))
    assert matches == [Path("apps/backend/container.py")]


def test_retrieval_and_infrastructure_do_not_import_backend() -> None:
    for package in (
        REPO_ROOT / "src" / "retrieval",
        REPO_ROOT / "src" / "infrastructure",
    ):
        for path in package.rglob("*.py"):
            imports = _imports(path)
            assert not any(
                name.startswith(("apps.backend", "api", "services")) for name in imports
            ), f"{path} imports backend module: {imports}"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names
