// =============================================================================
// Legal GraphRAG — Neo4j Schema Initialization
// Source of truth: plans/legal_ontology.md v1.3.0 (FROZEN 2026-07-07)
//
// Chạy 1 lần duy nhất sau khi Neo4j khởi động:
//   make init-schema
// hoặc thủ công:
//   docker exec -i graphrag-neo4j cypher-shell -u neo4j -p <password> < infra/neo4j/init/01_schema_init.cypher
//
// Lịch sử:
//   v1 (cũ) — dựa trên 02_ontology_specification.md (SUPERSEDED)
//   v2 (2026-07-07) — rewrite theo legal_ontology.md v1.3.0:
//     - Thêm Chapter, Issuer, LegalConcept, LegalSubject, LegalAction nodes
//     - Đổi AMENDED_BY/REPLACED_BY/REPEALED_BY → AMENDS/REPLACES/REPEALS (ADR-17)
//     - Đổi status → legal_status
//     - Thêm normative, issuer_name indexes cho Document
//     - Thêm effective_from/to + legal_status + embedding cho Article/Clause (F2)
//     - content → content_raw
// =============================================================================


// =============================================================================
// SECTION 1: UNIQUENESS CONSTRAINTS
// Structural Layer — legal_ontology.md §2.1
// =============================================================================

// --- Structural Layer ---
CREATE CONSTRAINT doc_id_unique     IF NOT EXISTS FOR (d:Document)     REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT ch_id_unique      IF NOT EXISTS FOR (c:Chapter)      REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT art_id_unique     IF NOT EXISTS FOR (a:Article)      REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT cls_id_unique     IF NOT EXISTS FOR (c:Clause)       REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT pnt_id_unique     IF NOT EXISTS FOR (p:Point)        REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT iss_id_unique    IF NOT EXISTS FOR (i:Issuer)       REQUIRE i.id IS UNIQUE;  // Rev.1: MERGE key = id (slug), không phải name (ADR-14 Rev.1)

// --- Semantic Layer --- legal_ontology.md §2.2
// Phase 1 scope: LegalConcept, LegalSubject, LegalAction (từ extraction Entity/Concept/Action)
// Obligation, Right, Condition, Exception — Future work (Out of scope)
CREATE CONSTRAINT lc_id_unique      IF NOT EXISTS FOR (c:LegalConcept) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT ls_id_unique      IF NOT EXISTS FOR (s:LegalSubject) REQUIRE s.id IS UNIQUE;
CREATE CONSTRAINT la_id_unique      IF NOT EXISTS FOR (a:LegalAction)  REQUIRE a.id IS UNIQUE;


// =============================================================================
// SECTION 2: LOOKUP INDEXES
// Tìm kiếm nhanh theo số hiệu, loại, trạng thái — legal_ontology.md §2.1
// =============================================================================

CREATE INDEX doc_number      IF NOT EXISTS FOR (d:Document) ON (d.number);
CREATE INDEX doc_doc_type    IF NOT EXISTS FOR (d:Document) ON (d.doc_type);
CREATE INDEX doc_normative   IF NOT EXISTS FOR (d:Document) ON (d.normative);       // filter văn bản quy phạm
CREATE INDEX doc_legal_status IF NOT EXISTS FOR (d:Document) ON (d.legal_status);  // đổi từ doc_status
CREATE INDEX doc_issuer_name IF NOT EXISTS FOR (d:Document) ON (d.issuer_name);    // Writer dùng để MERGE Issuer

CREATE INDEX art_number      IF NOT EXISTS FOR (a:Article) ON (a.number);
CREATE INDEX art_legal_status IF NOT EXISTS FOR (a:Article) ON (a.legal_status);   // F2: thêm mới
CREATE INDEX cls_legal_status IF NOT EXISTS FOR (c:Clause)  ON (c.legal_status);   // F2: thêm mới

CREATE INDEX issuer_name_idx IF NOT EXISTS FOR (i:Issuer) ON (i.name);


// =============================================================================
// SECTION 3: TEMPORAL INDEXES
// Dùng cho temporal filter trong Cypher query (RC4).
// Mọi truy vấn "văn bản còn hiệu lực tại ngày X" đều dùng indexes này.
// F2: Article/Clause cần effective_from/to vì retrieval query filter trực tiếp
//     trên node (xem 05_graphrag_retrieval.md Cypher templates).
// =============================================================================

CREATE INDEX doc_temporal IF NOT EXISTS FOR (d:Document) ON (d.effective_from, d.effective_to);
CREATE INDEX art_temporal IF NOT EXISTS FOR (a:Article)  ON (a.effective_from, a.effective_to);  // F2
CREATE INDEX cls_temporal IF NOT EXISTS FOR (c:Clause)   ON (c.effective_from, c.effective_to);  // F2

// Indexes trên relation properties (Neo4j 5.x) — ADR-17: active voice
CREATE INDEX amends_from   IF NOT EXISTS FOR ()-[r:AMENDS]-()   ON (r.effective_from);
CREATE INDEX replaces_from IF NOT EXISTS FOR ()-[r:REPLACES]-() ON (r.effective_from);
CREATE INDEX repeals_from  IF NOT EXISTS FOR ()-[r:REPEALS]-()  ON (r.effective_from);


// =============================================================================
// SECTION 4: FULL-TEXT SEARCH INDEX
// Hỗ trợ BM25 full-text search song song với vector search (ADR-08).
// Dùng content_raw (theo legal_ontology.md §2.1, không phải content).
// =============================================================================

CREATE FULLTEXT INDEX legal_fulltext IF NOT EXISTS
FOR (n:Article|Clause|Point)
ON EACH [n.content_raw, n.title];


// =============================================================================
// SECTION 5: VECTOR INDEXES (Neo4j 5.11+ native)
// 768 dims — khớp với vietnamese-bi-encoder (bkai-foundation-models).
// Cosine similarity — standard cho semantic search.
//
// ADR-08: Unified storage — không dùng Qdrant riêng biệt.
// 1 Cypher query = vector search + graph traversal + temporal filter.
//
// F2 + ADR-02: embedding nullable, chỉ có ở Article + Clause.
//   - Point: quá ngắn, không đủ ngữ cảnh để embed có ý nghĩa (ADR-02)
//   - Nullable: Writer ghi node trước (Tuần 1 M3), Embedding Generator fill sau (Tuần 2 M3)
//
// ⚠️  DIMENSION CONTRACT: 768 dim là schema contract, không phải tech detail.
//     Đổi embedding model → phải DROP INDEX + re-embed toàn bộ → cần ADR mới.
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
