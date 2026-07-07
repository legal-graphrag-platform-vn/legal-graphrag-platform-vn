# Legal GraphRAG Agent Guide

This repository builds a Vietnamese business-law Legal GraphRAG system.
The active contract is `plans/legal_ontology.md` v1.4.0. The `plans/` folder is the main map for understanding the project.

## Project Snapshot

The project has four layers of meaning:

1. `legal_ontology.md` defines the canonical graph contract.
2. The architecture and pipeline plans explain how text becomes a graph.
3. The retrieval and evaluation plans explain how the graph is used at query time.
4. The timeline, scope, and open questions track project progress and unresolved choices.

Current ingestion reality:

- The project crawls legal content from the web into `src/pipeline/data/raw/<doc_id>/`.
- Raw output is `metadata.json` plus `source.txt`.
- Parsing then converts raw data into `src/pipeline/data/processed/<doc_id>/`.
- Some older docs still say "PDF" because the corpus starts from legal documents, but the practical input to the pipeline is the crawled raw web data.

If you are new to the repo, start with `plans/README.md`, then read the ontology and the architecture docs that match your task.

## `plans/` Tree

```text
plans/
├── README.md
├── legal_ontology.md
├── 00_architecture_decisions.md
├── 01_research_contributions.md
├── 02_ontology_specification.md
├── 03_architecture.md
├── 04_graph_construction_pipeline.md
├── 05_graphrag_retrieval.md
├── 07_implementation_timeline.md
├── 08_dataset_and_scope.md
├── 09_open_questions.md
├── 10_tech_stack.md
├── 11_project_phases.md
├── 12_design_tradeoffs.md
└── 13_neo4j_integrity_strategy.md
```

## File Guide

### `plans/README.md`
Top-level index for the project. It gives the reading order, project status, and a quick view of which documents are current versus historical.

### `plans/legal_ontology.md`
The canonical ontology contract and source of truth. It defines the current node labels, relation names, required fields, validation boundaries, and the write-path stack.

### `plans/00_architecture_decisions.md`
The ADR log. It explains why the major design choices were made, with problem statements, considered options, final decisions, and trade-offs.

### `plans/01_research_contributions.md`
The research framing of the thesis. It maps the project to RC1-RC5 and explains the contribution structure in academic terms.

### `plans/02_ontology_specification.md`
Historical ontology document. It is kept for reference only and should not be treated as the active implementation contract.

### `plans/03_architecture.md`
High-level system architecture. It explains the layered design, the knowledge boundary between graph and runtime reasoning, and the overall retrieval flow.

### `plans/04_graph_construction_pipeline.md`
Detailed pipeline spec for turning crawled legal text into a validated graph. It covers crawler, parser, extraction, validation, scoring, and the Neo4j write handoff.

### `plans/05_graphrag_retrieval.md`
Retrieval design for the query-time system. It covers intent classification, hybrid retrieval, traversal policy, temporal handling, and explanation/citation behavior.

### `plans/07_implementation_timeline.md`
The working roadmap. It tracks implementation phases, milestones, dependencies, bugs to fix before later phases, and current progress.

### `plans/08_dataset_and_scope.md`
Corpus planning and scope definition. It lists the intended legal documents, the minimum dataset for the demo, the web-sourced corpus strategy, and the structure of the ground-truth annotation set.

### `plans/09_open_questions.md`
The unresolved decision log. It records the questions that still need project-level agreement, such as team allocation, dataset size, and baseline choices.

### `plans/10_tech_stack.md`
The technology selection doc. It records the chosen tools and libraries for graph storage, LLMs, embeddings, parsing, backend, frontend, and evaluation.

### `plans/11_project_phases.md`
The phase-gated project plan. It lays out what must be completed before each phase can start and what each phase must prove.

### `plans/12_design_tradeoffs.md`
The executive-summary version of the architecture trade-offs. It is useful for quick review and defense preparation.

### `plans/13_neo4j_integrity_strategy.md`
The write-path integrity note. It explains the Community Edition enforcement model and the split between application-layer validation and database bootstrap.

## How To Use The Plans

- Ontology or schema questions: read `plans/legal_ontology.md` first.
- Graph construction questions: read `plans/04_graph_construction_pipeline.md` and `plans/13_neo4j_integrity_strategy.md`.
- Raw ingestion or crawl questions: read `src/pipeline/main.py`, `src/pipeline/crawl_filtered.py`, and the crawler-related sections in `plans/04_graph_construction_pipeline.md`.
- Retrieval questions: read `plans/03_architecture.md` and `plans/05_graphrag_retrieval.md`.
- Roadmap or milestone questions: read `plans/07_implementation_timeline.md` and `plans/11_project_phases.md`.
- Scope or dataset questions: read `plans/08_dataset_and_scope.md`.
- Unresolved product or research decisions: read `plans/09_open_questions.md`.
- Architecture rationale: read `plans/00_architecture_decisions.md` and `plans/12_design_tradeoffs.md`.

## Reading Order For A New Agent

1. `plans/README.md`
2. `plans/legal_ontology.md`
3. `plans/03_architecture.md`
4. `plans/04_graph_construction_pipeline.md`
5. `plans/05_graphrag_retrieval.md`
6. `plans/07_implementation_timeline.md`
7. `plans/08_dataset_and_scope.md`
8. `plans/09_open_questions.md`

That order gives enough context to understand the project, the active ontology, the implementation path, and what is still open.
