from datetime import date
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class IntentType(str, Enum):
    FACTUAL = "factual"
    VALIDITY = "validity"
    HIERARCHY = "hierarchy"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    MULTI_HOP = "multi_hop"


class TemporalQuery(BaseModel):
    has_temporal: bool
    expression: Optional[str] = None
    resolved_from: Optional[date] = None
    resolved_to: Optional[date] = None
    granularity: Optional[str] = None


class RetrievedUnit(BaseModel):
    id: str
    label: Literal["Article", "Clause", "Point"]
    content_raw: str
    title: Optional[str] = None
    document_id: str
    document_number: Optional[str] = None
    article_number: Optional[str] = None
    clause_number: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    graph_score: Optional[float] = None
    rerank_score: Optional[float] = None
    final_score: Optional[float] = None
    citation_label: str


class GraphPath(BaseModel):
    nodes: List[str]
    relations: List[str]
    path_description: str
    is_temporal_valid: bool


class EvidenceItem(BaseModel):
    unit_id: str
    evidence_type: Literal["vector", "bm25", "graph", "temporal", "rerank"]
    matched_text: Optional[str] = None
    score: Optional[float] = None
    source_path_id: Optional[str] = None
    is_sufficient: bool = False


class RetrievalContext(BaseModel):
    query: str
    intent: IntentType
    temporal: TemporalQuery
    retrieved_units: List[RetrievedUnit]
    graph_paths: List[GraphPath]
    evidence: List[EvidenceItem]
    metrics: Dict[str, int]
    retrieval_mode: Literal[
        "vector_only",
        "vector_graph",
        "hybrid",
        "text_only_fallback"
    ]
    confidence_penalty: bool = False
