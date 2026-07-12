// TypeScript mirror của Pydantic models từ apps/backend/api/models.py
// Phải sync khi backend contract thay đổi.

export type DocumentLegalStatus =
  | "ACTIVE"
  | "NOT_YET_EFFECTIVE"
  | "PARTIALLY_EFFECTIVE"
  | "REPLACED"
  | "REPEALED"
  | "EXPIRED"

export interface PointDetail {
  id: string
  label: string
  content_raw: string
}

export interface ClauseDetail {
  id: string
  number: string
  content_raw: string
  points: PointDetail[]
}

export interface ArticleDetail {
  id: string
  number: string
  title?: string
  content_raw: string
  clauses: ClauseDetail[]
}

export interface ChapterDetail {
  id: string
  number: string
  title?: string
  articles: ArticleDetail[]
}

export interface DocumentRelation {
  doc_id: string
  doc_number: string
  relation_type: string
  affected_units: string[]
}

export interface DocumentSummary {
  id: string
  number: string
  title?: string
  doc_type: string
  issuer_name?: string
  issued_date?: string
  effective_from?: string
  status: DocumentLegalStatus
}

export interface DocumentDetail extends DocumentSummary {
  chapters: ChapterDetail[]
  ungrouped_articles: ArticleDetail[]
  relations: DocumentRelation[]
}

export interface ArticleResponse {
  document: DocumentSummary
  article: ArticleDetail
  related_units: DocumentRelation[]
}

export interface GraphNode {
  id: string
  label: string
  properties: Record<string, unknown>
}

export interface GraphEdge {
  source: string
  target: string
  relation_type: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: boolean
  total_nodes?: number
  total_edges?: number
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
}

export interface DocumentListResponse {
  items: DocumentSummary[]
  pagination: PageMeta
}

export interface RetrievedUnitDTO {
  id: string
  label: "Article" | "Clause" | "Point"
  content_raw: string
  citation_label: string
  document_id: string
  document_number?: string
  article_id?: string
  clause_id?: string
  effective_from?: string
  effective_to?: string
  final_score?: number
}

export interface FilterState {
  doc_type?: string
  issuer?: string
  status?: DocumentLegalStatus
  year?: number
}
