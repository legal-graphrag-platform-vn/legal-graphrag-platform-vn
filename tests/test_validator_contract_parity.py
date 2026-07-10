from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from src.validation import ontology_validator as root_v
from src.validation import payload_consistency_validator as root_payload_v


def _load_pipeline_validator():
    path = Path(__file__).resolve().parents[1] / "src/pipeline/src/validation/ontology_validator.py"
    spec = importlib.util.spec_from_file_location("pipeline_ontology_validator_for_parity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pipeline validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_pipeline_payload_validator():
    path = Path(__file__).resolve().parents[1] / "src/pipeline/src/validation/payload_consistency_validator.py"
    spec = importlib.util.spec_from_file_location("pipeline_payload_consistency_validator_for_parity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pipeline payload consistency validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline_v = _load_pipeline_validator()
pipeline_payload_v = _load_pipeline_payload_validator()


class ValidatorContractParityTests(unittest.TestCase):
    def test_pipeline_and_root_phase1_contracts_match(self) -> None:
        self.assertEqual(pipeline_v.RELATION_ENUM, root_v.PHASE1_RELATION_ENUM)
        self.assertEqual(pipeline_v.GUIDES_WHITELIST, root_v.GUIDES_WHITELIST)
        self.assertEqual(pipeline_v.ONTOLOGY_LABEL_MAP, root_v.ONTOLOGY_LABEL_MAP)
        self.assertEqual(pipeline_v.RUNTIME_ONLY_LABELS, root_v.RUNTIME_ONLY_LABELS)
        self.assertEqual(pipeline_v.PHASE1_PERSISTED_LABELS, root_v.PHASE1_PERSISTED_LABELS)
        self.assertEqual(
            set(pipeline_v.CONSTRAINTS["REQUIRES"]["valid_pairs"]),
            _root_allowed_pairs("REQUIRES"),
        )

    def test_legacy_aliases_rejected_by_both_validators(self) -> None:
        for alias in root_v.LEGACY_RELATION_ALIASES:
            pipeline_ok, _ = pipeline_v.validate_relation(
                "Article",
                alias,
                "Clause",
                properties={"effective_from": "2021-01-01"},
            )
            root_ok, _ = root_v.validate_relation(
                "Article",
                alias,
                "Clause",
                properties={"effective_from": "2021-01-01"},
            )
            self.assertFalse(pipeline_ok)
            self.assertFalse(root_ok)

    def test_pipeline_and_root_payload_consistency_contracts_match(self) -> None:
        self.assertEqual(pipeline_payload_v.STRUCTURAL_PAIRS, root_payload_v.STRUCTURAL_PAIRS)
        self.assertEqual(pipeline_payload_v.TEMPORAL_RELATIONS, root_payload_v.TEMPORAL_RELATIONS)
        self.assertEqual(
            pipeline_payload_v.deterministic_relation_id("ldn_2020", "CONTAINS", "ldn_2020_art17"),
            root_payload_v.deterministic_relation_id("ldn_2020", "CONTAINS", "ldn_2020_art17"),
        )

        payload = {
            "nodes": [
                {"type": "Document", "id": "ldn_2020"},
                {"type": "Article", "id": "ldn_2020_art17"},
            ],
            "relations": [
                {
                    "head_id": "ldn_2020",
                    "type": "CONTAINS",
                    "tail_id": "ldn_2020_art17",
                    "properties": {},
                }
            ],
        }
        self.assertFalse(pipeline_payload_v.validate_payload_consistency(payload).valid)
        self.assertFalse(root_payload_v.validate_payload_consistency(payload).valid)


def _root_allowed_pairs(relation_type: str) -> set[tuple[str, str]]:
    constraint = root_v.CONSTRAINTS[relation_type]
    if "valid_pairs" in constraint:
        return set(constraint["valid_pairs"])
    return {
        (head, tail)
        for head in constraint.get("allowed_head", [])
        for tail in constraint.get("allowed_tail", [])
    }

if __name__ == "__main__":
    unittest.main()
