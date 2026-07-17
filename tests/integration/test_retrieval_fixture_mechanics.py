from datetime import date

import pytest

from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.infrastructure.neo4j.writer import create_neo4j_session
from src.retrieval.models import IntentType, RetrievalFilters
from src.retrieval.retriever.graph import GraphRetriever


pytestmark = [pytest.mark.integration, pytest.mark.retrieval_fixture]


def test_uuid_fixture_graph_path_preserves_relation_identity(
    isolated_neo4j_prefix: str,
) -> None:
    prefix = isolated_neo4j_prefix
    document_id = f"{prefix}doc"
    source_id = f"{prefix}article_source"
    target_id = f"{prefix}article_target"
    relation_id = f"{prefix}refers_to"
    session = create_neo4j_session()
    try:
        session.run(
            """
            CREATE (document:Document {
              id: $document_id, number: 'test', title: 'test',
              doc_type: 'Law', legal_status: 'ACTIVE'
            })
            CREATE (source:Article {
              id: $source_id, number: '1', content_raw: 'source',
              effective_from: date($effective_from), legal_status: 'ACTIVE'
            })
            CREATE (target:Article {
              id: $target_id, number: '2', content_raw: 'target',
              effective_from: date($effective_from), legal_status: 'ACTIVE'
            })
            CREATE (document)-[:CONTAINS {relation_id: $contains_source}]->(source)
            CREATE (document)-[:CONTAINS {relation_id: $contains_target}]->(target)
            CREATE (source)-[:REFERS_TO {relation_id: $relation_id}]->(target)
            """,
            document_id=document_id,
            source_id=source_id,
            target_id=target_id,
            relation_id=relation_id,
            contains_source=f"{prefix}contains_source",
            contains_target=f"{prefix}contains_target",
            effective_from=date(2021, 1, 1).isoformat(),
        )
        expansion = GraphRetriever(Neo4jRetrieverRepo(session.driver)).expand(
            [source_id],
            IntentType.FACTUAL,
            filters=RetrievalFilters(document_ids=[document_id]),
        )
        assert expansion.paths
        assert relation_id in {edge.relation_id for edge in expansion.paths[0].edges}
        assert target_id in [unit.id for unit in expansion.units]
    finally:
        session.close()
