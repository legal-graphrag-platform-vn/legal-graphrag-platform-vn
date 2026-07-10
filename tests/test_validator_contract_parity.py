"""Parity tests: extraction_validator and write-time validators share the same
constants from shared.ontology.contract — no drift possible."""

from __future__ import annotations

import unittest

from src.shared.ontology import extraction_validator as extraction_v
from src.shared.ontology import validators as root_v
from src.shared.ontology import payload_consistency_validator as root_payload_v


class ValidatorContractParityTests(unittest.TestCase):
    def test_pipeline_and_root_phase1_contracts_match(self) -> None:
        # Both validators now import from contract.py — just verify they agree.
        self.assertEqual(extraction_v.RELATION_ENUM, root_v.RELATION_ENUM)
        self.assertEqual(extraction_v.GUIDES_WHITELIST, root_v.GUIDES_WHITELIST)
        self.assertEqual(extraction_v.ONTOLOGY_LABEL_MAP, root_v.ONTOLOGY_LABEL_MAP)
        self.assertEqual(extraction_v.RUNTIME_ONLY_LABELS, root_v.RUNTIME_ONLY_LABELS)
        self.assertEqual(extraction_v.PHASE1_PERSISTED_LABELS, root_v.PHASE1_PERSISTED_LABELS)
        self.assertEqual(extraction_v.CONSTRAINTS, root_v.CONSTRAINTS)

    def test_legacy_aliases_rejected_by_both_validators(self) -> None:
        for alias in root_v.LEGACY_RELATION_ALIASES:
            extraction_ok, _ = extraction_v.validate_relation(
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
            self.assertFalse(extraction_ok)
            self.assertFalse(root_ok)

    def test_payload_consistency_validator_available(self) -> None:
        self.assertTrue(hasattr(root_payload_v, "deterministic_relation_id"))
        self.assertTrue(hasattr(root_payload_v, "validate_payload_consistency"))
        self.assertTrue(hasattr(root_payload_v, "STRUCTURAL_PAIRS"))
        self.assertTrue(hasattr(root_payload_v, "TEMPORAL_RELATIONS"))
        relation_id = root_payload_v.deterministic_relation_id(
            "ldn_2020", "CONTAINS", "ldn_2020_art17"
        )
        self.assertIsInstance(relation_id, str)
        self.assertTrue(len(relation_id) > 0)





if __name__ == "__main__":
    unittest.main()
