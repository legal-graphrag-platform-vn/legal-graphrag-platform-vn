import unittest

from src.shared.ontology.validators import (
    CONSTRAINTS,
    RELATION_ENUM,
    GraphValidationError,
    OntologyValidator,
    validate_relation,
)


class OntologyConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = OntologyValidator()

    def test_all_relations_have_constraints(self) -> None:
        self.assertEqual(RELATION_ENUM, set(CONSTRAINTS.keys()))

    def test_document_requires_mandatory_fields(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_document(
                {
                    "type": "Document",
                    "id": "ldn_2020",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "issuer_name": "National Assembly",
                }
            )
        self.assertIn("effective_from", str(exc.exception))

    def test_document_requires_issuer_name(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_document(
                {
                    "type": "Document",
                    "id": "ldn_2020",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2021-01-01",
                }
            )
        self.assertIn("issuer_name", str(exc.exception))

    def test_document_requires_legal_status(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_document(
                {
                    "type": "Document",
                    "id": "ldn_2020",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "effective_from": "2021-01-01",
                    "issuer_name": "National Assembly",
                }
            )
        self.assertIn("legal_status", str(exc.exception))

    def test_article_requires_content_raw(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_article(
                {
                    "type": "Article",
                    "id": "ldn_2020_art17",
                    "number": "17",
                    "effective_from": "2021-01-01",
                    "legal_status": "ACTIVE",
                }
            )
        self.assertIn("content_raw", str(exc.exception))

    def test_article_requires_legal_status(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_article(
                {
                    "type": "Article",
                    "id": "ldn_2020_art17",
                    "number": "17",
                    "content_raw": "Some content",
                    "effective_from": "2021-01-01",
                }
            )
        self.assertIn("legal_status", str(exc.exception))

    def test_clause_requires_content_raw(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_clause(
                {
                    "type": "Clause",
                    "id": "ldn_2020_art17_cl1",
                    "number": "1",
                    "effective_from": "2021-01-01",
                    "legal_status": "ACTIVE",
                }
            )
        self.assertIn("content_raw", str(exc.exception))

    def test_clause_requires_legal_status(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_clause(
                {
                    "type": "Clause",
                    "id": "ldn_2020_art17_cl1",
                    "number": "1",
                    "content_raw": "Some content",
                    "effective_from": "2021-01-01",
                }
            )
        self.assertIn("legal_status", str(exc.exception))

    def test_structural_relations_accept_canonical_pairs(self) -> None:
        cases = [
            ("Document", "ISSUED_BY", "Issuer", {}),
            ("Document", "CONTAINS", "Chapter", {}),
            ("Chapter", "CONTAINS", "Article", {}),
            ("Document", "REPEALS", "Article", {"effective_from": "2021-01-01"}),
            ("Document", "REPLACES", "Document", {"effective_from": "2021-01-01"}),
            ("Article", "REFERS_TO", "Document", {"citation_text": "Điều 4", "citation_type": "DIRECT"}),
        ]

        for head_type, relation_type, tail_type, properties in cases:
            ok, error = validate_relation(head_type, relation_type, tail_type, properties=properties)
            self.assertTrue(ok, error)

    def test_semantic_relations_require_provenance(self) -> None:
        ok, error = validate_relation("Article", "DEFINES", "LegalConcept", properties={"confidence": 0.9})
        self.assertFalse(ok)
        self.assertIn("llm_model", error or "")

        provenance = {"confidence": 0.9, "llm_model": "test-model", "created_at": "2026-07-07T00:00:00Z"}
        cases = [
            ("Article", "DEFINES", "LegalConcept"),
            ("Clause", "REGULATES", "LegalSubject"),
            ("LegalSubject", "REQUIRES", "LegalConcept"),
            ("LegalAction", "HAS_CONDITION", "Condition"),
            ("Clause", "HAS_EXCEPTION", "Exception"),
        ]

        for head_type, relation_type, tail_type in cases:
            ok, error = validate_relation(head_type, relation_type, tail_type, properties=provenance)
            self.assertTrue(ok, error)

        ok, error = validate_relation("LegalSubject", "REQUIRES", "Obligation", properties=provenance)
        self.assertFalse(ok)
        self.assertIn("tail type Obligation", error or "")

    def test_runtime_only_nodes_are_not_phase1_persistent(self) -> None:
        with self.assertRaises(GraphValidationError) as exc:
            self.validator.validate_graph_payload(
                {
                    "nodes": [
                        {"type": "Obligation", "id": "obligation_1", "name": "Must register"},
                    ],
                    "relations": [],
                }
            )
        self.assertIn("Runtime-only node type", str(exc.exception))

    def test_temporal_relation_requires_effective_from(self) -> None:
        ok, error = validate_relation("Article", "AMENDS", "Clause", properties={})
        self.assertFalse(ok)
        self.assertIn("effective_from", error or "")

    def test_temporal_relation_passes_with_effective_from(self) -> None:
        ok, error = validate_relation(
            "Article",
            "AMENDS",
            "Clause",
            properties={"effective_from": "2021-01-01"},
        )
        self.assertTrue(ok, error)

    def test_guides_requires_document_whitelist(self) -> None:
        ok, error = validate_relation(
            "Document",
            "GUIDES",
            "Document",
            head_doc_type="Law",
            tail_doc_type="Decree",
        )
        self.assertTrue(ok, error)

        ok, error = validate_relation(
            "Document",
            "GUIDES",
            "Document",
            head_doc_type="Circular",
            tail_doc_type="Law",
        )
        self.assertFalse(ok)
        self.assertIn("GUIDES does not allow", error or "")

    def test_legacy_relation_aliases_are_rejected(self) -> None:
        ok, error = validate_relation(
            "Article",
            "AMENDED_BY",
            "Clause",
            properties={"effective_from": "2021-01-01"},
        )
        self.assertFalse(ok)
        self.assertIn("use canonical AMENDS", error or "")


if __name__ == "__main__":
    unittest.main()
