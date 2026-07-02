// =============================================================================
// Legal GraphRAG — Neo4j Schema Initialization
// Source of truth: plans/02_ontology_specification.md
//
// Chạy 1 lần duy nhất sau khi Neo4j khởi động:
//   make init-schema
// hoặc thủ công:
//   docker exec -i graphrag-neo4j cypher-shell -u neo4j -p <password> < infra/neo4j/init/01_schema_init.cypher
// =============================================================================


// =============================================================================
// SECTION 1: UNIQUENESS CONSTRAINTS
// Đảm bảo không có node trùng ID trong toàn graph.
// =============================================================================

CREATE CONSTRAINT doc_id_unique   IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT art_id_unique   IF NOT EXISTS FOR (a:Article)  REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT cls_id_unique   IF NOT EXISTS FOR (c:Clause)   REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT pnt_id_unique   IF NOT EXISTS FOR (p:Point)    REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT con_id_unique   IF NOT EXISTS FOR (c:Concept)  REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT ent_id_unique   IF NOT EXISTS FOR (e:Entity)   REQUIRE e.id IS UNIQUE;


// =============================================================================
// SECTION 2: LOOKUP INDEXES
// Tìm kiếm nhanh theo số hiệu văn bản và số điều.
// =============================================================================

CREATE INDEX doc_number   IF NOT EXISTS FOR (d:Document) ON (d.number);
CREATE INDEX art_number   IF NOT EXISTS FOR (a:Article)  ON (a.number);
CREATE INDEX doc_status   IF NOT EXISTS FOR (d:Document) ON (d.status);
CREATE INDEX art_status   IF NOT EXISTS FOR (a:Article)  ON (a.status);
CREATE INDEX cls_status   IF NOT EXISTS FOR (c:Clause)   ON (c.status);


// =============================================================================
// SECTION 3: TEMPORAL INDEXES
// Dùng cho temporal filter trong Cypher query (RC4).
// Mọi truy vấn "văn bản còn hiệu lực tại ngày X" đều dùng indexes này.
// =============================================================================

CREATE INDEX doc_temporal IF NOT EXISTS FOR (d:Document) ON (d.effective_from, d.effective_to);
CREATE INDEX art_temporal IF NOT EXISTS FOR (a:Article)  ON (a.effective_from, a.effective_to);
CREATE INDEX cls_temporal IF NOT EXISTS FOR (c:Clause)   ON (c.effective_from, c.effective_to);

// Indexes trên relationship properties (Neo4j 5.x)
CREATE INDEX amended_from  IF NOT EXISTS FOR ()-[r:AMENDED_BY]-()  ON (r.effective_from);
CREATE INDEX replaced_from IF NOT EXISTS FOR ()-[r:REPLACED_BY]-() ON (r.effective_from);
CREATE INDEX repealed_from IF NOT EXISTS FOR ()-[r:REPEALED_BY]-() ON (r.effective_from);


// =============================================================================
// SECTION 4: FULL-TEXT SEARCH INDEX
// Hỗ trợ BM25 full-text search song song với vector search.
// =============================================================================

CREATE FULLTEXT INDEX legal_fulltext IF NOT EXISTS
FOR (n:Article|Clause|Point)
ON EACH [n.content, n.title];


// =============================================================================
// SECTION 5: VECTOR INDEXES (Neo4j 5.11+ native)
// 768 dims — khớp với vietnamese-bi-encoder (bkai-foundation-models).
// Cosine similarity — standard cho semantic search.
//
// ADR-08: Unified storage — không dùng Qdrant riêng biệt.
// 1 Cypher query = vector search + graph traversal + temporal filter.
// =============================================================================

CREATE VECTOR INDEX article_embedding IF NOT EXISTS
FOR (a:Article) ON (a.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX clause_embedding IF NOT EXISTS
FOR (c:Clause) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};


// =============================================================================
// VERIFY — Chạy để xác nhận schema đã được tạo đúng
// =============================================================================

// SHOW CONSTRAINTS;
// SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties ORDER BY type;
// SHOW VECTOR INDEXES;
