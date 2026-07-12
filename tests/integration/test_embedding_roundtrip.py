import pytest
from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter
from src.infrastructure.neo4j.writer import create_neo4j_session

pytestmark = pytest.mark.integration

@pytest.fixture(autouse=True)
def setup_test_nodes():
    session = create_neo4j_session()
    try:
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_emb_' DETACH DELETE n")
        # Create test Article and Clause nodes in Neo4j
        session.run(
            "CREATE (a:Article {id: 'test_emb_doc_art1', number: '1', content_raw: 'Test Article content'})"
        )
        session.run(
            "CREATE (c:Clause {id: 'test_emb_doc_art1_cls1', number: '1', content_raw: 'Test Clause content'})"
        )
        yield
        session.run("MATCH (n) WHERE n.id STARTS WITH 'test_emb_' DETACH DELETE n")
    finally:
        session.close()

def test_embedding_generation_and_writing():
    session = create_neo4j_session()
    try:
        generator = EmbeddingGenerator()
        writer = Neo4jEmbeddingWriter(session=session)

        # Generate embeddings
        texts = ["Test Article content", "Test Clause content"]
        embeddings = generator.encode(texts)
        
        assert len(embeddings) == 2
        assert len(embeddings[0]) == 1024
        assert len(embeddings[1]) == 1024
        assert all(isinstance(val, float) for val in embeddings[0])

        # Write embeddings to Neo4j
        vectors_by_node_id = {
            "test_emb_doc_art1": list(embeddings[0]),
            "test_emb_doc_art1_cls1": list(embeddings[1]),
        }
        
        writer.verify_vector_indexes()
        writer.write_embeddings(vectors_by_node_id, graph_id="test_emb_doc")

        # Verify in DB
        res_art = list(session.run(
            "MATCH (a:Article {id: 'test_emb_doc_art1'}) RETURN a.embedding as emb"
        ))
        res_cls = list(session.run(
            "MATCH (c:Clause {id: 'test_emb_doc_art1_cls1'}) RETURN c.embedding as emb"
        ))
        
        assert res_art and res_art[0]["emb"] is not None
        assert len(res_art[0]["emb"]) == 1024
        assert res_cls and res_cls[0]["emb"] is not None
        assert len(res_cls[0]["emb"]) == 1024

    finally:
        session.close()
