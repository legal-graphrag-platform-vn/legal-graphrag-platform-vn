// =============================================================================
// Legal GraphRAG — Neo4j Schema Initialization
// Source of truth: plans/legal_ontology.md v1.8.0
//
// Script idempotent nhờ IF NOT EXISTS.
// =============================================================================

// =============================================================================
// SECTION 1: UNIQUENESS CONSTRAINTS
// =============================================================================

// --- Structural Layer ---
CREATE CONSTRAINT doc_id_unique IF NOT EXISTS
FOR (d:Document)
REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT part_id_unique IF NOT EXISTS
FOR (p:Part)
REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT ch_id_unique IF NOT EXISTS
FOR (c:Chapter)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT sec_id_unique IF NOT EXISTS
FOR (s:Section)
REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT subsec_id_unique IF NOT EXISTS
FOR (s:Subsection)
REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT art_id_unique IF NOT EXISTS
FOR (a:Article)
REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT cls_id_unique IF NOT EXISTS
FOR (c:Clause)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT pnt_id_unique IF NOT EXISTS
FOR (p:Point)
REQUIRE p.id IS UNIQUE;

CREATE CONSTRAINT iss_id_unique IF NOT EXISTS
FOR (i:Issuer)
REQUIRE i.id IS UNIQUE;

// --- Semantic Layer ---
CREATE CONSTRAINT lc_id_unique IF NOT EXISTS
FOR (c:LegalConcept)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT ls_id_unique IF NOT EXISTS
FOR (s:LegalSubject)
REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT la_id_unique IF NOT EXISTS
FOR (a:LegalAction)
REQUIRE a.id IS UNIQUE;

// =============================================================================
// SECTION 2: LOOKUP INDEXES
// =============================================================================

CREATE INDEX doc_number IF NOT EXISTS
FOR (d:Document)
ON (d.number);

CREATE INDEX doc_doc_type IF NOT EXISTS
FOR (d:Document)
ON (d.doc_type);

CREATE INDEX doc_normative IF NOT EXISTS
FOR (d:Document)
ON (d.normative);

CREATE INDEX doc_legal_status IF NOT EXISTS
FOR (d:Document)
ON (d.legal_status);

CREATE INDEX doc_issuer_name IF NOT EXISTS
FOR (d:Document)
ON (d.issuer_name);

CREATE INDEX art_number IF NOT EXISTS
FOR (a:Article)
ON (a.number);

CREATE INDEX art_legal_status IF NOT EXISTS
FOR (a:Article)
ON (a.legal_status);

CREATE INDEX cls_legal_status IF NOT EXISTS
FOR (c:Clause)
ON (c.legal_status);

CREATE INDEX pnt_legal_status IF NOT EXISTS
FOR (p:Point)
ON (p.legal_status);

CREATE INDEX issuer_name_idx IF NOT EXISTS
FOR (i:Issuer)
ON (i.name);

// =============================================================================
// SECTION 2.5: SEMANTIC LOOKUP INDEXES
// =============================================================================

CREATE INDEX lc_name IF NOT EXISTS
FOR (c:LegalConcept)
ON (c.name);

CREATE INDEX ls_name IF NOT EXISTS
FOR (s:LegalSubject)
ON (s.name);

CREATE INDEX la_name IF NOT EXISTS
FOR (a:LegalAction)
ON (a.name);

// =============================================================================
// SECTION 3: TEMPORAL INDEXES
// =============================================================================

CREATE INDEX doc_temporal IF NOT EXISTS
FOR (d:Document)
ON (d.effective_from, d.effective_to);

CREATE INDEX art_temporal IF NOT EXISTS
FOR (a:Article)
ON (a.effective_from, a.effective_to);

CREATE INDEX cls_temporal IF NOT EXISTS
FOR (c:Clause)
ON (c.effective_from, c.effective_to);

CREATE INDEX pnt_temporal IF NOT EXISTS
FOR (p:Point)
ON (p.effective_from, p.effective_to);

CREATE INDEX amends_from IF NOT EXISTS
FOR ()-[r:AMENDS]-()
ON (r.effective_from);

CREATE INDEX replaces_from IF NOT EXISTS
FOR ()-[r:REPLACES]-()
ON (r.effective_from);

CREATE INDEX repeals_from IF NOT EXISTS
FOR ()-[r:REPEALS]-()
ON (r.effective_from);

// =============================================================================
// SECTION 3.5: RELATION IDENTITY INDEXES
// =============================================================================

CREATE INDEX issued_by_relation_id IF NOT EXISTS
FOR ()-[r:ISSUED_BY]-()
ON (r.relation_id);

CREATE INDEX contains_relation_id IF NOT EXISTS
FOR ()-[r:CONTAINS]-()
ON (r.relation_id);

CREATE INDEX refers_to_relation_id IF NOT EXISTS
FOR ()-[r:REFERS_TO]-()
ON (r.relation_id);

CREATE INDEX guides_relation_id IF NOT EXISTS
FOR ()-[r:GUIDES]-()
ON (r.relation_id);

CREATE INDEX amends_relation_id IF NOT EXISTS
FOR ()-[r:AMENDS]-()
ON (r.relation_id);

CREATE INDEX repeals_relation_id IF NOT EXISTS
FOR ()-[r:REPEALS]-()
ON (r.relation_id);

CREATE INDEX replaces_relation_id IF NOT EXISTS
FOR ()-[r:REPLACES]-()
ON (r.relation_id);

CREATE INDEX defines_relation_id IF NOT EXISTS
FOR ()-[r:DEFINES]-()
ON (r.relation_id);

CREATE INDEX regulates_relation_id IF NOT EXISTS
FOR ()-[r:REGULATES]-()
ON (r.relation_id);

CREATE INDEX requires_relation_id IF NOT EXISTS
FOR ()-[r:REQUIRES]-()
ON (r.relation_id);

// =============================================================================
// SECTION 4: FULL-TEXT SEARCH INDEXES
// =============================================================================

CREATE FULLTEXT INDEX legal_article_clause_fulltext IF NOT EXISTS
FOR (n:Article|Clause)
ON EACH [n.content_raw, n.title];

CREATE FULLTEXT INDEX legal_point_fulltext IF NOT EXISTS
FOR (p:Point)
ON EACH [p.content_raw];

// =============================================================================
// SECTION 5: VECTOR INDEXES (Neo4j 5.11+ native, 1024-dim BAAI/bge-m3)
// =============================================================================

CREATE VECTOR INDEX article_embedding IF NOT EXISTS
FOR (a:Article)
ON (a.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX clause_embedding IF NOT EXISTS
FOR (c:Clause)
ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};
