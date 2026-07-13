# L59_2020 Retrieval Runtime v1 Pilot Development Results

> Evaluation scope: `pilot_development`
> Runtime contract: `retrieval-runtime-v1`
> Gate 7 / M3-B13: OPEN
> Milestone A: NOT PASSED
> Milestone B acceptance: NOT STARTED

## Reproducibility

- Base source commit: `91b222ce0c14cd9cc95a91c710429b4b57cd03cf`
- Working tree at evaluation: `dirty` (development evidence, not sign-off evidence)
- Historical dataset: `configs/evaluation/retrieval_pilot_l59_2020_legacy.json`
- Dataset SHA-256: `5394b2f6cd8c71148c6e9b408a4098e5eabe9960f710bdcf261a4803b9c5f09e`
- Router config SHA-256: `3a4239708e055db41ba1b9527a78218f5777a43c5009447f2867fd1e444fab0c`
- Neo4j graph snapshot SHA-256: `67d0318fbb32b3c0f7ad9b4842515b2c5cd074f4021cebba32338103795f0091`
- Embedding contract: `flag_embedding:BAAI/bge-m3:1024`
- Reranker contract: disabled
- Machine-readable report: `results/retrieval/runtime_v1_pilot_development.json`

## Runtime Profile

- Document filter: `ldn_2020`
- Seed channels: vector + full-text
- Graph expansion: exactly once after seed RRF
- Final fusion: vector + full-text + graph-derived ranked list through RRF
- RRF: deterministic, `k=60`, unit ID tie-break
- Full-text index: `legal_article_clause_fulltext`

## Results

| Profile | Sample | Recall@5 | MRR | nDCG@5 | No-results rate |
|---|---:|---:|---:|---:|---:|
| Runtime-v1 hybrid | 3 | 0.6012 | 1.0000 | 0.7847 | 0.0000 |

Development latency distribution is recorded in the JSON report with its sample
size. It is not production latency evidence.

## Limitations

- Three curated queries are below the 30-query pilot target.
- This historical dataset uses the pre-v1 list schema and is retained only to
  reproduce the development smoke hash. New evaluation uses
  `retrieval-evaluation-dataset-v1`.
- The gold IDs are not a held-out thesis evaluation set.
- Only the hybrid runtime profile was rerun under `retrieval-runtime-v1`.
- Reranked and full ablation profiles remain open.
- Temporal, hierarchy, and comparison cases may be reported as unsupported when
  the pilot lacks their required graph capabilities.
- Gate 7 corpus expansion remains open, so these results cannot satisfy
  Milestone A or Milestone B acceptance.
