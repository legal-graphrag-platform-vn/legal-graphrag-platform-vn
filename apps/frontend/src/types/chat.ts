/**
 * Source maps to RetrievedUnitDTO from backend API.
 * Giữ backward compat với title/content cho SourceDetailModal.
 */
export interface Source {
   // Backward compat fields
   id: string
   title: string    // = citation_label
   content: string  // = content_raw
   // Legacy modal fields (still used by SourceDetailModal)
   url?: string
   page?: string
   score?: number
   // New fields from RetrievedUnitDTO
   citation_label?: string
   label?: 'Article' | 'Clause' | 'Point'
   document_id?: string
   document_number?: string
   article_id?: string
   clause_id?: string
   effective_from?: string
   effective_to?: string
   final_score?: number
}

export interface Message {
   id: string
   role: 'user' | 'assistant'
   content: string
   sources?: Source[]
   timestamp: string
   // Metadata từ event: metadata
   intent?: string
   retrieval_mode?: string
   error?: string
}

export interface ChatSession {
   id: string
   title: string
   messages: Message[]
   createdAt: string
}
