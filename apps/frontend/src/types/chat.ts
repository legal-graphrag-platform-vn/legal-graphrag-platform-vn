/**
 * Source maps to RetrievedUnitDTO from backend API.
 * Giữ backward compat với title/content cho SourceDetailModal.
 */
export interface Source {
   // Backward compat fields
   id: string
   title: string // = citation_label
   content: string // = content_raw
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
   deep_link?: string
   ordinal?: number
}

export interface ReasoningPath {
   path_id: string
   description: string
   nodes: string[]
}

export interface Message {
   id: string
   role: 'user' | 'assistant'
   content: string
   sources?: Source[]
   timestamp: string
   // Idempotency (Plan 19): mỗi user turn giữ client_turn_id ổn định qua retry.
   client_turn_id?: string
   // Phân loại turn phía server: câu trả lời, cần làm rõ, hay đang xử lý.
   kind?: 'answer' | 'clarification' | 'processing'
   resolution_status?: string
   // Metadata từ event: metadata
   intent?: string
   retrieval_mode?: string
   error?: string
   // Server không đủ căn cứ để trả lời — kèm lý do (nếu có).
   cannot_answer?: boolean
   insufficiency_message?: string
   temporal_notes?: string[]
   reasoning_paths?: ReasoningPath[]
}

/**
 * ChatSession.id CHÍNH LÀ conversation_id gửi lên server (Plan 19 §5).
 * LocalStorage chỉ là UI cache — server mới là nguồn context authority.
 */
export interface ChatSession {
   id: string
   title: string
   messages: Message[]
   createdAt: string
}
