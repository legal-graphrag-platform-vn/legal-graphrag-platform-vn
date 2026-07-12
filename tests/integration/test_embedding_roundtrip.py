import pytest
from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator
from src.infrastructure.embedding.embedding_generator import embedding_content_hash
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter
from src.infrastructure.neo4j.writer import create_neo4j_session

pytestmark = pytest.mark.integration

@pytest.fixture()
def embedding_nodes(isolated_neo4j_prefix):
    graph_id = f"{isolated_neo4j_prefix}doc"
    article_id = f"{graph_id}_art1"
    clause_id = f"{graph_id}_art1_cl1"
    session = create_neo4j_session()
    try:
        session.run("CREATE (d:Document {id: $id})", id=graph_id)
        session.run(
            "CREATE (a:Article {id: $id, number: '1', content_raw: 'Test Article content'})", id=article_id
        )
        session.run(
            "CREATE (c:Clause {id: $id, number: '1', content_raw: 'Test Clause content'})", id=clause_id
        )
        session.run(
            "MATCH (d:Document {id: $doc_id}), (a:Article {id: $article_id}), (c:Clause {id: $clause_id}) "
            "CREATE (d)-[:CONTAINS]->(a)-[:CONTAINS]->(c)",
            doc_id=graph_id,
            article_id=article_id,
            clause_id=clause_id,
        )
        yield graph_id, article_id, clause_id
    finally:
        session.close()

def test_embedding_generation_and_writing(embedding_nodes):
    graph_id, article_id, clause_id = embedding_nodes
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
            article_id: list(embeddings[0]),
            clause_id: list(embeddings[1]),
        }
        
        writer.verify_vector_indexes()
        writer.write_embeddings(
            vectors_by_node_id,
            graph_id=graph_id,
            content_hashes={
                article_id: embedding_content_hash(texts[0]),
                clause_id: embedding_content_hash(texts[1]),
            },
            model="BAAI/bge-m3",
            provider="flag_embedding",
        )

        # Verify in DB
        res_art = list(session.run(
            "MATCH (a:Article {id: $id}) RETURN a.embedding as emb", id=article_id
        ))
        res_cls = list(session.run(
            "MATCH (c:Clause {id: $id}) RETURN c.embedding as emb", id=clause_id
        ))
        
        assert res_art and res_art[0]["emb"] is not None
        assert len(res_art[0]["emb"]) == 1024
        assert res_cls and res_cls[0]["emb"] is not None
        assert len(res_cls[0]["emb"]) == 1024

    finally:
        session.close()
