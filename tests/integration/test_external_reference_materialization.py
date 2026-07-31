from __future__ import annotations

import pytest

from src.infrastructure.neo4j.reference_writer import Neo4jExternalReferenceWriter
from src.infrastructure.neo4j.writer import (
    GraphIngestionService,
    Neo4jWriter,
    create_neo4j_session,
)
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)
from src.shared.ontology.validators import (
    ValidatedExternalReference,
    ValidatedRelation,
    validate_external_relation_batch,
)


pytestmark = pytest.mark.integration


def test_external_reference_is_idempotent_and_crosses_documents(
    isolated_neo4j_prefix,
) -> None:
    prefix = isolated_neo4j_prefix
    source_doc = f"{prefix}source_doc"
    source_article = f"{prefix}source_art1"
    target_doc = f"{prefix}target_doc"
    target_article = f"{prefix}target_art35"
    session = create_neo4j_session()
    try:
        ingestion = GraphIngestionService(writer=Neo4jWriter(session=session))
        for doc_id, article_id, number in (
            (source_doc, source_article, "1"),
            (target_doc, target_article, "35"),
        ):
            contains_id = deterministic_relation_id(doc_id, "CONTAINS", article_id)
            ingestion.ingest(
                {
                    "nodes": [
                        {
                            "type": "Document",
                            "id": doc_id,
                            "doc_type": "Law",
                            "number": f"{number}/2026/QH15",
                            "normative": True,
                            "legal_status": "ACTIVE",
                            "effective_from": "2026-01-01",
                            "issuer_name": "Quốc hội",
                        },
                        {
                            "type": "Article",
                            "id": article_id,
                            "number": number,
                            "content_raw": "Nội dung",
                            "effective_from": "2026-01-01",
                            "legal_status": "ACTIVE",
                        },
                    ],
                    "relations": [
                        {
                            "head_id": doc_id,
                            "type": "CONTAINS",
                            "tail_id": article_id,
                            "properties": {"relation_id": contains_id},
                        }
                    ],
                }
            )

        properties = {
            "citation_text": "Điều 35 Luật số 35/2026/QH15",
            "citation_type": "DIRECT",
            "extraction_method": "ENTITY_LINKING",
            "created_at": "2026-07-31T00:00:00+00:00",
            "reference_bundle_id": f"{prefix}bundle",
            "reference_target_count": 1,
            "source_unit_id": source_article,
            "source_char_start": 0,
            "source_char_end": 34,
            "linker_name": "corpus-structural-registry",
            "linker_version": "1.0.0",
        }
        discriminator = relation_identity_discriminator("REFERS_TO", properties)
        properties["relation_id"] = deterministic_relation_id(
            source_article, "REFERS_TO", target_article, discriminator
        )
        relation = ValidatedRelation(
            head_id=source_article,
            relation_type="REFERS_TO",
            tail_id=target_article,
            head_type="Article",
            tail_type="Article",
            properties=properties,
        )
        wrapped = ValidatedExternalReference(
            relation=relation,
            source_id=source_article,
            source_type="Article",
            source_document_id=source_doc,
            source_ancestor_ids=(source_doc,),
            target_id=target_article,
            target_type="Article",
            target_document_id=target_doc,
            target_ancestor_ids=(target_doc,),
            reference_bundle_id=f"{prefix}bundle",
        )
        batch = validate_external_relation_batch(
            [wrapped],
            registry_build_id="integration-build",
            registry_snapshot_hash="sha256:" + "1" * 64,
            registry_provenance_hash="sha256:" + "2" * 64,
        )

        writer = Neo4jExternalReferenceWriter(session)
        writer.write(batch)
        writer.write(batch)

        rows = list(
            session.run(
                "MATCH (s {id: $source})-[r:REFERS_TO]->(t {id: $target}) "
                "RETURN count(r) AS count",
                source=source_article,
                target=target_article,
            )
        )
        assert rows[0]["count"] == 1
    finally:
        session.close()
