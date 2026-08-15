// Legal GraphRAG ontology migration: 1.12.0 -> 1.13.0 (ADR-35)
// Run only after application writers/readers have been upgraded to 1.13.0.

CREATE CONSTRAINT appendix_id_unique IF NOT EXISTS
FOR (a:Appendix)
REQUIRE a.id IS UNIQUE;

CREATE INDEX appendix_number IF NOT EXISTS
FOR (a:Appendix)
ON (a.number);

CREATE INDEX appendix_kind IF NOT EXISTS
FOR (a:Appendix)
ON (a.appendix_kind);

CREATE INDEX appendix_legal_status IF NOT EXISTS
FOR (a:Appendix)
ON (a.legal_status);

CREATE INDEX appendix_temporal IF NOT EXISTS
FOR (a:Appendix)
ON (a.effective_from, a.effective_to);

CREATE VECTOR INDEX appendix_embedding IF NOT EXISTS
FOR (a:Appendix)
ON (a.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};

// Neo4j cannot alter the label set of an existing full-text index in place.
DROP INDEX legal_article_clause_fulltext IF EXISTS;

CREATE FULLTEXT INDEX legal_article_clause_fulltext IF NOT EXISTS
FOR (n:Appendix|Article|Clause)
ON EACH [n.content_raw, n.title];
