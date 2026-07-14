import { apiGet } from './client'
import type {
   ArticleResponse,
   DocumentDetail,
   DocumentListResponse,
   FilterState,
   GraphData,
} from '@/types/documents'

export const documentsApi = {
   list: (page = 1, pageSize = 20, filters: FilterState = {}): Promise<DocumentListResponse> =>
      apiGet<DocumentListResponse>('/api/v1/documents', {
         page: String(page),
         page_size: String(pageSize),
         doc_type: filters.doc_type,
         issuer: filters.issuer,
         status: filters.status,
         year: filters.year !== undefined ? String(filters.year) : undefined,
      }),

   getDetail: (docId: string): Promise<DocumentDetail> =>
      apiGet<DocumentDetail>(`/api/v1/documents/${docId}`),

   getGraph: (
      docId: string,
      opts: { depth?: number; nodeLimit?: number; edgeLimit?: number } = {},
   ): Promise<GraphData> =>
      apiGet<GraphData>(`/api/v1/documents/${docId}/graph`, {
         depth: String(opts.depth ?? 1),
         node_limit: String(opts.nodeLimit ?? 100),
         edge_limit: String(opts.edgeLimit ?? 300),
      }),

   getArticle: (articleId: string): Promise<ArticleResponse> =>
      apiGet<ArticleResponse>(`/api/v1/articles/${articleId}`),
}
