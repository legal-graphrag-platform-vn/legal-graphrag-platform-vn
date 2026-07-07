import unittest
from unittest.mock import Mock
from unittest.mock import patch

from src.database.neo4j_writer import GraphIngestionService, Neo4jWriter, WriteAttemptError
from src.validation.ontology_validator import GraphValidationError, OntologyValidator


class WriterGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = Mock()
        self.writer = Neo4jWriter(session=self.session)
        self.validator = OntologyValidator()
        self.service = GraphIngestionService(validator=self.validator, writer=self.writer)

    def test_invalid_payload_never_reaches_merge(self) -> None:
        payload = {
            "nodes": [
                {
                    "type": "Document",
                    "id": "ldn_2020",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "issuer_name": "National Assembly",
                }
            ],
            "relations": [],
        }

        with self.assertRaises(GraphValidationError):
            self.service.ingest(payload)

        self.assertEqual(self.session.run.call_count, 0)

    def test_valid_payload_is_written_successfully(self) -> None:
        payload = {
            "nodes": [
                {
                    "type": "Document",
                    "id": "ldn_2020",
                    "doc_type": "Law",
                    "number": "59/2020/QH14",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2021-01-01",
                    "issuer_name": "National Assembly",
                },
                {
                    "type": "Article",
                    "id": "ldn_2020_art17",
                    "number": "17",
                    "content_raw": "Article content",
                    "effective_from": "2021-01-01",
                    "legal_status": "ACTIVE",
                },
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

        validated = self.service.ingest(payload)
        self.assertEqual(len(validated.nodes), 2)
        self.assertEqual(len(validated.relations), 1)
        self.assertGreater(self.session.run.call_count, 0)

    def test_raw_write_attempt_is_rejected(self) -> None:
        with self.assertRaises(WriteAttemptError):
            self.writer.write({"nodes": [], "relations": []})  # type: ignore[arg-type]

    def test_ingest_calls_shared_validation_gate(self) -> None:
        with patch.object(
            self.validator,
            "validate_graph_payload",
            wraps=self.validator.validate_graph_payload,
        ) as validate_spy:
            self.service.ingest(
                {
                    "nodes": [
                        {
                            "type": "Document",
                            "id": "ldn_2020",
                            "doc_type": "Law",
                            "number": "59/2020/QH14",
                            "normative": True,
                            "legal_status": "ACTIVE",
                            "effective_from": "2021-01-01",
                            "issuer_name": "National Assembly",
                        },
                        {
                            "type": "Article",
                            "id": "ldn_2020_art17",
                            "number": "17",
                            "content_raw": "Article content",
                            "effective_from": "2021-01-01",
                            "legal_status": "ACTIVE",
                        },
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
            )

        self.assertEqual(validate_spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
