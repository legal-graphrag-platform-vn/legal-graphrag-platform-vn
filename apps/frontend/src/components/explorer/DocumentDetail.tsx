'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import type { DocumentDetail, ArticleDetail, ChapterDetail } from '@/types/documents'
import { useDocumentGraph } from '@/hooks/useDocumentGraph'

// GraphViewer chỉ load khi user click tab "Đồ thị" — lazy + client-only
const GraphViewer = dynamic(() => import('./GraphViewer'), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center text-sm text-foreground/40">
      Đang tải đồ thị...
    </div>
  ),
})

type Tab = 'content' | 'relations' | 'graph'

const RELATION_LABELS: Record<string, string> = {
  AMENDS: 'Sửa đổi', REPLACES: 'Thay thế', REPEALS: 'Hủy bỏ',
  GUIDES: 'Hướng dẫn', REFERS_TO: 'Tham chiếu', REQUIRES: 'Yêu cầu',
}

function ClauseAccordion({ article, highlightClauseId }: { article: ArticleDetail; highlightClauseId?: string }) {
  return (
    <div className="ml-4 mt-2 space-y-2">
      {article.clauses.map((clause) => (
        <div
          key={clause.id}
          id={clause.id}
          className={`text-xs leading-relaxed p-2 rounded ${
            clause.id === highlightClauseId ? 'bg-brand/10 border border-brand/30' : ''
          }`}
        >
          <span className="font-medium text-foreground/70">{clause.number}. </span>
          <span className="text-foreground/80">{clause.content_raw}</span>
          {clause.points.map((pt) => (
            <div key={pt.id} className="ml-3 mt-1 text-foreground/60">
              <span className="font-medium">{pt.label} </span>{pt.content_raw}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function ArticleAccordion({
  article,
  highlightArticleId,
  highlightClauseId,
}: {
  article: ArticleDetail
  highlightArticleId?: string
  highlightClauseId?: string
}) {
  const [open, setOpen] = useState(article.id === highlightArticleId)

  return (
    <div
      key={article.id}
      id={article.id}
      className={`border border-border rounded mb-2 ${
        article.id === highlightArticleId ? 'border-brand/50' : ''
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2 hover:bg-foreground/5 transition-colors"
      >
        <span className="text-brand mt-0.5">{open ? '▼' : '▶'}</span>
        <div>
          <span className="text-xs font-semibold text-foreground">
            Điều {article.number}
            {article.title ? `. ${article.title}` : ''}
          </span>
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3">
          {article.content_raw && (
            <p className="text-xs text-foreground/70 mb-2">{article.content_raw}</p>
          )}
          {article.clauses.length > 0 && (
            <ClauseAccordion article={article} highlightClauseId={highlightClauseId} />
          )}
        </div>
      )}
    </div>
  )
}

interface DocumentDetailProps {
  doc: DocumentDetail
  highlightArticleId?: string
  highlightClauseId?: string
  onNavigateDoc?: (docId: string) => void
}

export function DocumentDetailPanel({
  doc,
  highlightArticleId,
  highlightClauseId,
  onNavigateDoc,
}: DocumentDetailProps) {
  const [activeTab, setActiveTab] = useState<Tab>('content')
  const [graphEnabled, setGraphEnabled] = useState(false)

  const { graph, isLoading: graphLoading, error: graphError } = useDocumentGraph(
    doc.id,
    graphEnabled,
  )

  const handleTabClick = (tab: Tab) => {
    setActiveTab(tab)
    // Lazy load: chỉ fetch graph khi user click tab "Đồ thị" lần đầu
    if (tab === 'graph') setGraphEnabled(true)
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'content', label: 'Nội dung' },
    { id: 'relations', label: 'Quan hệ văn bản' },
    { id: 'graph', label: 'Đồ thị' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <p className="text-xs text-brand font-semibold">{doc.number}</p>
        {doc.title && (
          <h2 className="text-sm font-bold text-foreground mt-1 leading-snug">{doc.title}</h2>
        )}
        <div className="flex flex-wrap gap-2 mt-2 text-[11px] text-foreground/50">
          {doc.issuer_name && <span>{doc.issuer_name}</span>}
          {doc.effective_from && (
            <span>Hiệu lực từ {new Date(doc.effective_from).toLocaleDateString('vi-VN')}</span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border shrink-0">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => handleTabClick(tab.id)}
            className={`px-4 py-2 text-xs font-medium transition-colors border-b-2 ${
              activeTab === tab.id
                ? 'border-brand text-brand'
                : 'border-transparent text-foreground/50 hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {/* Tab: Nội dung */}
        {activeTab === 'content' && (
          <div className="p-4">
            {doc.chapters.map((ch) => (
              <div key={ch.id} className="mb-6">
                <h3 className="text-xs font-bold uppercase text-foreground/60 mb-3">
                  Chương {ch.number}{ch.title ? ` — ${ch.title}` : ''}
                </h3>
                {ch.articles.map((art) => (
                  <ArticleAccordion
                    key={art.id}
                    article={art}
                    highlightArticleId={highlightArticleId}
                    highlightClauseId={highlightClauseId}
                  />
                ))}
              </div>
            ))}
            {doc.ungrouped_articles.map((art) => (
              <ArticleAccordion
                key={art.id}
                article={art}
                highlightArticleId={highlightArticleId}
                highlightClauseId={highlightClauseId}
              />
            ))}
          </div>
        )}

        {/* Tab: Quan hệ văn bản */}
        {activeTab === 'relations' && (
          <div className="p-4">
            {doc.relations.length === 0 ? (
              <p className="text-xs text-foreground/40 text-center mt-8">
                Không có quan hệ văn bản nào
              </p>
            ) : (
              <div className="space-y-2">
                {doc.relations.map((rel, i) => (
                  <button
                    key={i}
                    onClick={() => onNavigateDoc?.(rel.doc_id)}
                    className="w-full text-left p-3 rounded border border-border hover:border-brand/40 hover:bg-brand/5 transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-foreground/10 text-foreground/60 shrink-0">
                        {RELATION_LABELS[rel.relation_type] ?? rel.relation_type}
                      </span>
                      <span className="text-xs font-semibold text-brand group-hover:underline">
                        {rel.doc_number}
                      </span>
                    </div>
                    {rel.affected_units.length > 0 && (
                      <p className="text-[10px] text-foreground/50 mt-1 ml-1">
                        Liên quan: {rel.affected_units.join(', ')}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab: Đồ thị — lazy load */}
        {activeTab === 'graph' && (
          <div className="h-full min-h-[400px]">
            {graphLoading && (
              <div className="flex items-center justify-center h-full text-sm text-foreground/40">
                Đang tải đồ thị...
              </div>
            )}
            {graphError && (
              <div className="flex items-center justify-center h-full text-sm text-red-500">
                {graphError}
              </div>
            )}
            {graph && !graphLoading && (
              <GraphViewer data={graph} onNodeClick={onNavigateDoc} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
