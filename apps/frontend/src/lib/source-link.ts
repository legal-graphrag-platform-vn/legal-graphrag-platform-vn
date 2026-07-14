import type { Source } from '@/types/chat'

export function sourceHref(source: Source): string | null {
   if (source.deep_link?.startsWith('/explorer')) return source.deep_link
   if (!source.document_id) return null
   const params = new URLSearchParams({ document: source.document_id })
   if (source.article_id) params.set('article', source.article_id)
   if (source.clause_id) params.set('clause', source.clause_id)
   return `/explorer?${params.toString()}`
}
