import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _imports_under(path: Path) -> set[str]:
    imports: set[str] = set()
    for source_path in path.rglob("*.py"):
        if "tests" in source_path.parts:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_retrieval_does_not_import_concrete_layers() -> None:
    imports = _imports_under(ROOT / "src" / "retrieval")
    forbidden = ("src.infrastructure", "src.pipeline", "apps", "prototypes")
    assert not sorted(name for name in imports if name.startswith(forbidden))


def test_infrastructure_does_not_import_retrieval() -> None:
    imports = _imports_under(ROOT / "src" / "infrastructure")
    assert not sorted(name for name in imports if name.startswith("src.retrieval"))


def test_only_one_intent_type_definition_exists() -> None:
    definitions: list[Path] = []
    for source_path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef) and node.name == "IntentType"
            for node in tree.body
        ):
            definitions.append(source_path)
    assert definitions == [ROOT / "src" / "shared" / "retrieval_contract.py"]
