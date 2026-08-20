import type { Source } from '@/types/chat'

export function sourceHref(source: Source): string | null {
   if (source.deep_link?.startsWith('/explorer')) return source.deep_link
   if (!source.document_id) return null
   // Appendix has no article_id/clause_id (it belongs directly to the
   // Document, not nested under an Article/Clause) and /explorer has no
   // section to render it in yet — return null so the caller falls back to
   // the detail modal, which already shows the full content correctly,
   // instead of navigating to a document page with no indication of it.
   if (source.label === 'Appendix') return null
   const params = new URLSearchParams({ document: source.document_id })
   if (source.article_id) params.set('article', source.article_id)
   if (source.clause_id) params.set('clause', source.clause_id)
   return `/explorer?${params.toString()}`
}
