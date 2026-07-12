import pytest
from src.pipeline.config import settings
from src.infrastructure.neo4j.writer import create_neo4j_session
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter

pytestmark = pytest.mark.integration

def test_neo4j_constraints_and_indexes():
    session = create_neo4j_session()
    try:
        # Verify Constraints
        constraint_rows = list(session.run("SHOW CONSTRAINTS"))
        names = {row["name"] for row in constraint_rows}
        expected_constraints = {
            "doc_id_unique",
            "ch_id_unique",
            "art_id_unique",
            "cls_id_unique",
            "pnt_id_unique",
            "iss_id_unique",
        }
        missing = expected_constraints - names
        assert not missing, f"Missing required uniqueness constraints: {missing}"

        # Verify Vector Indexes
        writer = Neo4jEmbeddingWriter(session=session)
        writer.verify_vector_indexes()

        # Detailed Verification of dimensions and similarity
        index_rows = list(session.run(
            "SHOW INDEXES YIELD name, type, state, options WHERE type = 'VECTOR'"
        ))
        
        indexes = {row["name"]: row for row in index_rows}
        assert "article_embedding" in indexes
        assert "clause_embedding" in indexes

        for name in ("article_embedding", "clause_embedding"):
            idx = indexes[name]
            assert idx["state"] == "ONLINE"
            options = idx["options"]
            assert isinstance(options, dict)
            config = options.get("indexConfig") or {}
            assert config.get("vector.dimensions") == 1024, f"{name} dimension mismatch"
            assert config.get("vector.similarity_function", "").lower() == "cosine", f"{name} similarity mismatch"

    finally:
        session.close()
import pytest

pytestmark = pytest.mark.integration
