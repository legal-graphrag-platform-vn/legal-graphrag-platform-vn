// Legal GraphRAG ontology migration: 1.13.0 -> 1.14.0 (ADR-36)
// Run only after application writers/readers have been upgraded to 1.14.0.

CREATE CONSTRAINT attached_instrument_id_unique IF NOT EXISTS
FOR (a:AttachedInstrument)
REQUIRE a.id IS UNIQUE;

CREATE INDEX attached_instrument_scope IF NOT EXISTS
FOR (a:AttachedInstrument)
ON (a.scope);

CREATE INDEX attached_instrument_kind IF NOT EXISTS
FOR (a:AttachedInstrument)
ON (a.instrument_kind);
