"""Immutable corpus-wide registry of accepted structural legal endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.pipeline.parser.hierarchy_parser import canonicalize_source_text
from src.shared.ontology.contract import ONTOLOGY_VERSION
from src.shared.ontology.hierarchy import (
    normalize_chapter_number,
    normalize_section_number,
)
from src.shared.ontology.validators import ValidatedGraphPayload, ValidatedNode


REGISTRY_CONTRACT_VERSION = "corpus-structural-registry-v1"
REGISTRY_BUILD_CONTRACT_VERSION = "corpus-structural-registry-build-v1"
REGISTRY_CANONICALIZATION_VERSION = "registry-canonical-json-v1"
PARSER_CONTRACT_VERSION = "hierarchy-parser-v1.7"
HIERARCHY_CONTRACT_VERSION = "document-hierarchy-v1.7"
VALIDATOR_VERSION = "ontology-validator-v1.7"

STRUCTURAL_TYPES = frozenset(
    {"Document", "Chapter", "Section", "Article", "Clause", "Point"}
)
UNIT_TYPES = frozenset(STRUCTURAL_TYPES - {"Document"})
ALLOWED_CONTAINS_PAIRS = frozenset(
    {
        ("Document", "Chapter"),
        ("Document", "Article"),
        ("Chapter", "Section"),
        ("Chapter", "Article"),
        ("Section", "Article"),
        ("Article", "Clause"),
        ("Clause", "Point"),
    }
)
_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HASH_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


class RegistryError(ValueError):
    """Raised when registry content or publication violates the contract."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RegistryContentManifest(_FrozenModel):
    contract_version: Literal["corpus-structural-registry-v1"] = (
        REGISTRY_CONTRACT_VERSION
    )
    snapshot_hash: str
    ontology_version: str
    canonicalization_version: str
    document_count: int = Field(ge=1)
    structural_unit_count: int = Field(ge=0)
    contains_relation_count: int = Field(ge=0)


class RegistrySourceArtifact(_FrozenModel):
    raw_doc_code: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    canonical_source_digest: str
    validated_structural_projection_digest: str


class RegistryBuildReceipt(_FrozenModel):
    contract_version: Literal["corpus-structural-registry-build-v1"] = (
        REGISTRY_BUILD_CONTRACT_VERSION
    )
    build_id: str
    snapshot_hash: str
    provenance_hash: str
    parser_contract_version: str
    hierarchy_contract_version: str
    validator_version: str
    source_artifacts: tuple[RegistrySourceArtifact, ...]
    created_at: datetime


class RegistryDocument(_FrozenModel):
    document_id: str = Field(min_length=1)
    number: str = Field(min_length=1)
    normalized_number: str = Field(min_length=1)
    doc_type: str = Field(min_length=1)


class RegistryUnit(_FrozenModel):
    unit_id: str = Field(min_length=1)
    unit_type: Literal["Chapter", "Section", "Article", "Clause", "Point"]
    document_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    ancestor_ids: tuple[str, ...]
    chapter_number: str | None = None
    section_number: str | None = None
    article_number: str | None = None
    clause_number: str | None = None
    point_label: str | None = None


RegistryEndpoint = RegistryDocument | RegistryUnit


@dataclass(frozen=True, slots=True)
class RegistryBuild:
    registry: "CorpusStructuralRegistry"
    receipt: RegistryBuildReceipt


class CorpusStructuralRegistry:
    """Loaded content snapshot with exact candidate-preserving indexes."""

    def __init__(
        self,
        manifest: RegistryContentManifest,
        documents: Sequence[RegistryDocument],
        units: Sequence[RegistryUnit],
    ) -> None:
        self.manifest = manifest
        self.documents = tuple(documents)
        self.units = tuple(units)
        self._validate_content()

        documents_by_number: dict[str, list[RegistryDocument]] = defaultdict(list)
        endpoints_by_id: dict[str, list[RegistryEndpoint]] = defaultdict(list)
        units_by_key: dict[tuple[str, ...], list[RegistryUnit]] = defaultdict(list)
        for document in self.documents:
            documents_by_number[document.normalized_number].append(document)
            endpoints_by_id[document.document_id].append(document)
        for unit in self.units:
            endpoints_by_id[unit.unit_id].append(unit)
            units_by_key[structural_key(unit)].append(unit)

        self._documents_by_number = {
            key: tuple(sorted(values, key=lambda item: item.document_id))
            for key, values in documents_by_number.items()
        }
        self._endpoints_by_id = {
            key: tuple(values) for key, values in endpoints_by_id.items()
        }
        self._units_by_key = {
            key: tuple(sorted(values, key=lambda item: item.unit_id))
            for key, values in units_by_key.items()
        }

    @property
    def snapshot_hash(self) -> str:
        return self.manifest.snapshot_hash

    def document_candidates(self, number: str) -> tuple[RegistryDocument, ...]:
        return self._documents_by_number.get(normalize_document_number(number), ())

    def endpoint_candidates(self, endpoint_id: str) -> tuple[RegistryEndpoint, ...]:
        return self._endpoints_by_id.get(endpoint_id, ())

    def unit_candidates(
        self,
        *,
        document_id: str,
        unit_type: str,
        chapter_number: str | None = None,
        section_number: str | None = None,
        article_number: str | None = None,
        clause_number: str | None = None,
        point_label: str | None = None,
    ) -> tuple[RegistryUnit, ...]:
        key = structural_lookup_key(
            document_id=document_id,
            unit_type=unit_type,
            chapter_number=chapter_number,
            section_number=section_number,
            article_number=article_number,
            clause_number=clause_number,
            point_label=point_label,
        )
        return self._units_by_key.get(key, ())

    def _validate_content(self) -> None:
        if self.manifest.contract_version != REGISTRY_CONTRACT_VERSION:
            raise RegistryError(
                f"Unsupported registry contract: {self.manifest.contract_version}"
            )
        expected_hash = registry_snapshot_hash(self.documents, self.units)
        if self.manifest.snapshot_hash != expected_hash:
            raise RegistryError(
                "Registry snapshot hash mismatch: "
                f"expected {expected_hash}, got {self.manifest.snapshot_hash}"
            )
        if self.manifest.document_count != len(self.documents):
            raise RegistryError("Registry document_count does not match documents")
        if self.manifest.structural_unit_count != len(self.units):
            raise RegistryError("Registry structural_unit_count does not match units")
        if self.manifest.contains_relation_count != len(self.units):
            raise RegistryError(
                "Every registry unit must have exactly one canonical parent"
            )

        endpoint_ids = [item.document_id for item in self.documents] + [
            item.unit_id for item in self.units
        ]
        duplicate_ids = _duplicates(endpoint_ids)
        if duplicate_ids:
            raise RegistryError(
                f"Duplicate registry endpoint IDs: {', '.join(duplicate_ids)}"
            )


def build_corpus_registry(
    payloads: Mapping[str, ValidatedGraphPayload],
    canonical_sources: Mapping[str, str],
    *,
    build_id: str,
    created_at: datetime | None = None,
) -> RegistryBuild:
    """Build content and provenance from root-validated graph payloads."""

    _validate_build_id(build_id)
    if not payloads:
        raise RegistryError("At least one validated payload is required")
    if set(payloads) != set(canonical_sources):
        raise RegistryError("Validated payload and canonical source selections differ")

    all_documents: list[RegistryDocument] = []
    all_units: list[RegistryUnit] = []
    artifacts: list[RegistrySourceArtifact] = []

    for raw_doc_code in sorted(payloads):
        payload = payloads[raw_doc_code]
        if not isinstance(payload, ValidatedGraphPayload):
            raise RegistryError("Registry builder accepts only ValidatedGraphPayload")
        documents, units = _project_payload(payload)
        if len(documents) != 1:
            raise RegistryError(
                f"{raw_doc_code} must contain exactly one accepted Document"
            )
        document = documents[0]
        all_documents.append(document)
        all_units.extend(units)
        artifacts.append(
            RegistrySourceArtifact(
                raw_doc_code=raw_doc_code,
                document_id=document.document_id,
                canonical_source_digest=_hash_text(
                    canonicalize_source_text(canonical_sources[raw_doc_code])
                ),
                validated_structural_projection_digest=_projection_digest(
                    documents, units
                ),
            )
        )

    all_documents.sort(key=lambda item: item.document_id)
    all_units.sort(key=lambda item: item.unit_id)
    snapshot_hash = registry_snapshot_hash(all_documents, all_units)
    manifest = RegistryContentManifest(
        snapshot_hash=snapshot_hash,
        ontology_version=ONTOLOGY_VERSION,
        canonicalization_version=REGISTRY_CANONICALIZATION_VERSION,
        document_count=len(all_documents),
        structural_unit_count=len(all_units),
        contains_relation_count=len(all_units),
    )
    registry = CorpusStructuralRegistry(manifest, all_documents, all_units)
    ordered_artifacts = tuple(sorted(artifacts, key=lambda item: item.document_id))
    provenance_hash = registry_provenance_hash(snapshot_hash, ordered_artifacts)
    receipt = RegistryBuildReceipt(
        build_id=build_id,
        snapshot_hash=snapshot_hash,
        provenance_hash=provenance_hash,
        parser_contract_version=PARSER_CONTRACT_VERSION,
        hierarchy_contract_version=HIERARCHY_CONTRACT_VERSION,
        validator_version=VALIDATOR_VERSION,
        source_artifacts=ordered_artifacts,
        created_at=created_at or datetime.now(timezone.utc),
    )
    return RegistryBuild(registry=registry, receipt=receipt)


def registry_snapshot_hash(
    documents: Sequence[RegistryDocument], units: Sequence[RegistryUnit]
) -> str:
    payload = {
        "contract_version": REGISTRY_CONTRACT_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "canonicalization_version": REGISTRY_CANONICALIZATION_VERSION,
        "documents": [
            item.model_dump(mode="json")
            for item in sorted(documents, key=lambda value: value.document_id)
        ],
        "units": [
            item.model_dump(mode="json")
            for item in sorted(units, key=lambda value: value.unit_id)
        ],
    }
    return _hash_json(payload)


def registry_provenance_hash(
    snapshot_hash: str, artifacts: Sequence[RegistrySourceArtifact]
) -> str:
    _hash_hex(snapshot_hash)
    payload = {
        "parser_contract_version": PARSER_CONTRACT_VERSION,
        "hierarchy_contract_version": HIERARCHY_CONTRACT_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "snapshot_hash": snapshot_hash,
        "sources": [
            {
                "document_id": item.document_id,
                "canonical_source_digest": item.canonical_source_digest,
                "validated_structural_projection_digest": (
                    item.validated_structural_projection_digest
                ),
            }
            for item in sorted(artifacts, key=lambda value: value.document_id)
        ],
    }
    return _hash_json(payload)


def publish_registry_build(build: RegistryBuild, root: Path) -> Path:
    """Durably publish content then receipt, and switch the current pointer."""

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    content_root = root / "content"
    builds_root = root / "builds"
    content_root.mkdir(exist_ok=True)
    builds_root.mkdir(exist_ok=True)
    _validate_build_id(build.receipt.build_id)
    snapshot_hex = _hash_hex(build.receipt.snapshot_hash)
    content_dir = content_root / snapshot_hex
    build_dir = builds_root / build.receipt.build_id

    if content_dir.exists():
        loaded = _load_content(content_dir)
        if loaded.snapshot_hash != build.registry.snapshot_hash:
            raise RegistryError("Existing registry content directory is inconsistent")
    else:
        staging = Path(tempfile.mkdtemp(prefix=".content-", dir=content_root))
        try:
            _write_json_durable(
                staging / "content_manifest.json",
                build.registry.manifest.model_dump(mode="json"),
            )
            _write_jsonl_durable(
                staging / "documents.jsonl",
                (item.model_dump(mode="json") for item in build.registry.documents),
            )
            _write_jsonl_durable(
                staging / "units.jsonl",
                (item.model_dump(mode="json") for item in build.registry.units),
            )
            _fsync_directory(staging)
            os.replace(staging, content_dir)
            _fsync_directory(content_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    if build_dir.exists():
        existing = RegistryBuildReceipt.model_validate_json(
            (build_dir / "build_receipt.json").read_text(encoding="utf-8")
        )
        if existing != build.receipt:
            raise RegistryError(
                f"Build ID already exists with different receipt: {build.receipt.build_id}"
            )
    else:
        staging = Path(tempfile.mkdtemp(prefix=".build-", dir=builds_root))
        try:
            _write_json_durable(
                staging / "build_receipt.json",
                build.receipt.model_dump(mode="json"),
            )
            _fsync_directory(staging)
            os.replace(staging, build_dir)
            _fsync_directory(builds_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    pointer = root / "current_reference_registry"
    temporary_pointer = root / f".current_reference_registry.{os.getpid()}.tmp"
    if temporary_pointer.exists() or temporary_pointer.is_symlink():
        temporary_pointer.unlink()
    temporary_pointer.symlink_to(Path("builds") / build.receipt.build_id)
    os.replace(temporary_pointer, pointer)
    _fsync_directory(root)
    return build_dir


def load_registry_build(root: Path, build_id: str | None = None) -> RegistryBuild:
    root = root.resolve()
    if build_id is None:
        pointer = root / "current_reference_registry"
        if not pointer.is_symlink():
            raise RegistryError("Current registry pointer is missing or not a symlink")
        resolved = pointer.resolve(strict=True)
        builds_root = (root / "builds").resolve(strict=True)
        if resolved.parent != builds_root:
            raise RegistryError("Current registry pointer escapes builds directory")
        build_dir = resolved
    else:
        _validate_build_id(build_id)
        build_dir = root / "builds" / build_id
    if build_dir.is_symlink() or not build_dir.is_dir():
        raise RegistryError(f"Registry build does not exist: {build_dir}")

    receipt = RegistryBuildReceipt.model_validate_json(
        (build_dir / "build_receipt.json").read_text(encoding="utf-8")
    )
    if receipt.build_id != build_dir.name:
        raise RegistryError("Registry build receipt ID does not match directory")
    expected_provenance = registry_provenance_hash(
        receipt.snapshot_hash, receipt.source_artifacts
    )
    if receipt.provenance_hash != expected_provenance:
        raise RegistryError("Registry provenance hash mismatch")
    content_dir = root / "content" / _hash_hex(receipt.snapshot_hash)
    registry = _load_content(content_dir)
    if registry.snapshot_hash != receipt.snapshot_hash:
        raise RegistryError("Build receipt points to different registry content")
    return RegistryBuild(registry=registry, receipt=receipt)


def normalize_document_number(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip().upper()
    normalized = re.sub(r"\s+", "", normalized)
    if not normalized:
        raise RegistryError("Document number must not be blank")
    return normalized


def normalize_legal_number(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).strip().lower()
    normalized = re.sub(r"\s+", "", normalized)
    if not re.fullmatch(r"\d+[a-z]?", normalized):
        raise RegistryError(f"Unsupported structural number: {value!r}")
    return normalized


def normalize_point(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip().lower()
    if not re.fullmatch(r"[a-zđ]", normalized):
        raise RegistryError(f"Unsupported legal point label: {value!r}")
    return normalized


def structural_key(unit: RegistryUnit) -> tuple[str, ...]:
    return structural_lookup_key(
        document_id=unit.document_id,
        unit_type=unit.unit_type,
        chapter_number=unit.chapter_number,
        section_number=unit.section_number,
        article_number=unit.article_number,
        clause_number=unit.clause_number,
        point_label=unit.point_label,
    )


def structural_lookup_key(
    *,
    document_id: str,
    unit_type: str,
    chapter_number: str | None = None,
    section_number: str | None = None,
    article_number: str | None = None,
    clause_number: str | None = None,
    point_label: str | None = None,
) -> tuple[str, ...]:
    if unit_type == "Chapter":
        if chapter_number is None:
            raise RegistryError("Chapter lookup requires chapter_number")
        return (document_id, unit_type, normalize_chapter_number(chapter_number))
    if unit_type == "Section":
        if chapter_number is None or section_number is None:
            raise RegistryError("Section lookup requires chapter and section")
        return (
            document_id,
            unit_type,
            normalize_chapter_number(chapter_number),
            normalize_section_number(section_number),
        )
    if unit_type == "Article":
        if article_number is None:
            raise RegistryError("Article lookup requires article_number")
        return (document_id, unit_type, normalize_legal_number(article_number))
    if unit_type == "Clause":
        if article_number is None or clause_number is None:
            raise RegistryError("Clause lookup requires article and clause")
        return (
            document_id,
            unit_type,
            normalize_legal_number(article_number),
            normalize_legal_number(clause_number),
        )
    if unit_type == "Point":
        if article_number is None or clause_number is None or point_label is None:
            raise RegistryError("Point lookup requires article, clause, and point")
        return (
            document_id,
            unit_type,
            normalize_legal_number(article_number),
            normalize_legal_number(clause_number),
            normalize_point(point_label),
        )
    raise RegistryError(f"Unsupported structural unit type: {unit_type}")


def _project_payload(
    payload: ValidatedGraphPayload,
) -> tuple[list[RegistryDocument], list[RegistryUnit]]:
    node_index = {
        node.id: node for node in payload.nodes if node.node_type in STRUCTURAL_TYPES
    }
    documents = [node for node in node_index.values() if node.node_type == "Document"]
    if len(documents) != 1:
        raise RegistryError("Each validated payload must contain exactly one Document")
    document_node = documents[0]

    parents: dict[str, list[str]] = defaultdict(list)
    for relation in payload.relations:
        if relation.relation_type != "CONTAINS":
            continue
        head = node_index.get(relation.head_id)
        tail = node_index.get(relation.tail_id)
        if head is None or tail is None:
            continue
        pair = (head.node_type, tail.node_type)
        if pair not in ALLOWED_CONTAINS_PAIRS:
            raise RegistryError(f"Invalid structural CONTAINS pair: {pair}")
        parents[tail.id].append(head.id)

    units: list[RegistryUnit] = []
    for node in sorted(node_index.values(), key=lambda item: item.id):
        if node.node_type == "Document":
            continue
        unit_parents = parents.get(node.id, [])
        if len(unit_parents) != 1:
            raise RegistryError(
                f"Structural unit {node.id} must have exactly one canonical parent"
            )
        parent_id = unit_parents[0]
        ancestor_ids = _ancestor_chain(node.id, parent_id, parents, node_index)
        if not ancestor_ids or ancestor_ids[0] != document_node.id:
            raise RegistryError(
                f"Structural unit {node.id} is not owned by Document {document_node.id}"
            )
        units.append(
            _registry_unit(node, parent_id, ancestor_ids, node_index, document_node.id)
        )

    registered = {document_node.id, *(unit.unit_id for unit in units)}
    unregistered = sorted(set(node_index) - registered)
    if unregistered:
        raise RegistryError(f"Unregistered structural units: {', '.join(unregistered)}")
    return (
        [
            RegistryDocument(
                document_id=document_node.id,
                number=str(document_node.properties["number"]),
                normalized_number=normalize_document_number(
                    str(document_node.properties["number"])
                ),
                doc_type=str(document_node.properties["doc_type"]),
            )
        ],
        units,
    )


def _ancestor_chain(
    unit_id: str,
    parent_id: str,
    parents: Mapping[str, list[str]],
    node_index: Mapping[str, ValidatedNode],
) -> tuple[str, ...]:
    reverse_chain: list[str] = []
    seen = {unit_id}
    current = parent_id
    while True:
        if current in seen:
            raise RegistryError(f"Structural cycle detected at {current}")
        seen.add(current)
        reverse_chain.append(current)
        node = node_index.get(current)
        if node is None:
            raise RegistryError(f"Missing structural parent: {current}")
        if node.node_type == "Document":
            break
        candidates = parents.get(current, [])
        if len(candidates) != 1:
            raise RegistryError(
                f"Structural parent {current} must have exactly one canonical parent"
            )
        current = candidates[0]
    return tuple(reversed(reverse_chain))


def _registry_unit(
    node: ValidatedNode,
    parent_id: str,
    ancestor_ids: tuple[str, ...],
    node_index: Mapping[str, ValidatedNode],
    document_id: str,
) -> RegistryUnit:
    chain_nodes = [node_index[item] for item in ancestor_ids] + [node]

    def number_for(node_type: str, property_name: str = "number") -> str | None:
        candidates = [item for item in chain_nodes if item.node_type == node_type]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise RegistryError(f"Ambiguous {node_type} ancestry for {node.id}")
        value = candidates[0].properties.get(property_name)
        if value in (None, ""):
            raise RegistryError(f"Missing {node_type}.{property_name} for {node.id}")
        return str(value)

    return RegistryUnit(
        unit_id=node.id,
        unit_type=node.node_type,
        document_id=document_id,
        parent_id=parent_id,
        ancestor_ids=ancestor_ids,
        chapter_number=number_for("Chapter"),
        section_number=number_for("Section"),
        article_number=number_for("Article"),
        clause_number=number_for("Clause"),
        point_label=number_for("Point", "label"),
    )


def _projection_digest(
    documents: Sequence[RegistryDocument], units: Sequence[RegistryUnit]
) -> str:
    return _hash_json(
        {
            "documents": [item.model_dump(mode="json") for item in documents],
            "units": [
                item.model_dump(mode="json")
                for item in sorted(units, key=lambda value: value.unit_id)
            ],
        }
    )


def _load_content(content_dir: Path) -> CorpusStructuralRegistry:
    if content_dir.is_symlink() or not content_dir.is_dir():
        raise RegistryError(f"Registry content does not exist: {content_dir}")
    manifest = RegistryContentManifest.model_validate_json(
        (content_dir / "content_manifest.json").read_text(encoding="utf-8")
    )
    documents = tuple(
        RegistryDocument.model_validate(row)
        for row in _read_jsonl(content_dir / "documents.jsonl")
    )
    units = tuple(
        RegistryUnit.model_validate(row)
        for row in _read_jsonl(content_dir / "units.jsonl")
    )
    return CorpusStructuralRegistry(manifest, documents, units)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        raise RegistryError(f"Registry file missing or unsafe: {path}")
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"Invalid JSONL at {path}:{line_number}") from exc
        if not isinstance(raw, dict):
            raise RegistryError(
                f"Registry JSONL row must be an object: {path}:{line_number}"
            )
        rows.append(raw)
    return rows


def _write_json_durable(path: Path, payload: Mapping[str, object]) -> None:
    _write_bytes_durable(path, (_canonical_json(payload) + "\n").encode("utf-8"))


def _write_jsonl_durable(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    content = "".join(f"{_canonical_json(row)}\n" for row in rows)
    _write_bytes_durable(path, content.encode("utf-8"))


def _write_bytes_durable(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_json(payload: object) -> str:
    return _hash_text(_canonical_json(payload))


def _hash_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _hash_hex(value: str) -> str:
    match = _HASH_RE.fullmatch(value)
    if not match:
        raise RegistryError(f"Invalid SHA-256 digest: {value!r}")
    return match.group(1)


def _validate_build_id(build_id: str) -> None:
    if not _BUILD_ID_RE.fullmatch(build_id):
        raise RegistryError(f"Unsafe registry build ID: {build_id!r}")


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate)
