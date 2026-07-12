'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import type { DocumentDetail, ArticleDetail, GraphData } from '@/types/documents'
import { useDocumentGraph } from '@/hooks/useDocumentGraph'

// GraphViewer: client-only + lazy (chỉ import khi tab Đồ thị được click)
const GraphViewer = dynamic(() => import('./GraphViewer'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <Skeleton className="w-full h-full rounded-none" />
    </div>
  ),
})

const RELATION_LABELS: Record<string, string> = {
  AMENDS: 'Sửa đổi', REPLACES: 'Thay thế', REPEALS: 'Hủy bỏ',
  GUIDES: 'Hướng dẫn', REFERS_TO: 'Tham chiếu', REQUIRES: 'Yêu cầu',
  ISSUED_BY: 'Ban hành bởi',
}

function ClauseItem({
  clause,
  highlighted,
}: {
  clause: ArticleDetail['clauses'][0]
  highlighted: boolean
}) {
  return (
    <div
      id={clause.id}
      className={`text-xs leading-relaxed py-1.5 px-2 rounded-sm transition-colors ${
        highlighted ? 'bg-primary/8 ring-1 ring-primary/30' : ''
      }`}
    >
      <span className="font-medium text-muted-foreground">{clause.number}. </span>
      <span>{clause.content_raw}</span>
      {clause.points.map((pt) => (
        <div key={pt.id} className="ml-4 mt-1 text-muted-foreground">
          <span className="font-medium">{pt.label} </span>
          {pt.content_raw}
        </div>
      ))}
    </div>
  )
}

function ArticleItem({
  article,
  highlightArticleId,
  highlightClauseId,
}: {
  article: ArticleDetail
  highlightArticleId?: string
  highlightClauseId?: string
}) {
  const isHighlighted = article.id === highlightArticleId
  const [open, setOpen] = useState(isHighlighted)

  return (
    <div
      id={article.id}
      className={`border rounded-md mb-2 overflow-hidden transition-colors ${
        isHighlighted ? 'border-primary/40 bg-primary/3' : 'border-border'
      }`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-3 py-2.5 flex items-center gap-2 hover:bg-muted/50 transition-colors"
      >
        {open
          ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        }
        <span className="text-xs font-semibold">
          Điều {article.number}
          {article.title ? `. ${article.title}` : ''}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-1">
          {article.content_raw && !article.clauses.length && (
            <p className="text-xs text-muted-foreground">{article.content_raw}</p>
          )}
          {article.clauses.map((cl) => (
            <ClauseItem
              key={cl.id}
              clause={cl}
              highlighted={cl.id === highlightClauseId}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface DocumentDetailPanelProps {
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
}: DocumentDetailPanelProps) {
  const [graphEnabled, setGraphEnabled] = useState(false)
  const { graph, isLoading: graphLoading } = useDocumentGraph(doc.id, graphEnabled)

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 py-4 border-b border-border bg-card shrink-0">
        <Badge variant="outline" className="text-xs font-mono mb-2">
          {doc.number}
        </Badge>
        {doc.title && (
          <h2 className="text-base font-bold leading-snug mt-1">{doc.title}</h2>
        )}
        <div className="flex flex-wrap gap-3 mt-2 text-xs text-muted-foreground">
          {doc.issuer_name && <span>{doc.issuer_name}</span>}
          {doc.effective_from && (
            <>
              <Separator orientation="vertical" className="h-3 self-center" />
              <span>
                Hiệu lực từ {new Date(doc.effective_from).toLocaleDateString('vi-VN')}
              </span>
            </>
          )}
          {doc.doc_type && (
            <>
              <Separator orientation="vertical" className="h-3 self-center" />
              <Badge variant="secondary" className="text-[10px] h-4">
                {doc.doc_type}
              </Badge>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        defaultValue="content"
        className="flex-1 flex flex-col overflow-hidden"
        onValueChange={(v) => { if (v === 'graph') setGraphEnabled(true) }}
      >
        <TabsList className="rounded-none border-b border-border bg-muted/30 justify-start px-4 h-9 shrink-0">
          <TabsTrigger value="content" className="text-xs h-7 px-3">Nội dung</TabsTrigger>
          <TabsTrigger value="relations" className="text-xs h-7 px-3">
            Quan hệ
            {doc.relations.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 text-[9px] h-3.5 px-1">
                {doc.relations.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="graph" className="text-xs h-7 px-3">Đồ thị</TabsTrigger>
        </TabsList>

        {/* Tab: Nội dung */}
        <TabsContent value="content" className="flex-1 overflow-hidden m-0">
          <ScrollArea className="h-full">
            <div className="p-4">
              {doc.chapters.map((ch) => (
                <div key={ch.id} className="mb-6">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
                    Chương {ch.number}{ch.title ? ` — ${ch.title}` : ''}
                  </p>
                  {ch.articles.map((art) => (
                    <ArticleItem
                      key={art.id}
                      article={art}
                      highlightArticleId={highlightArticleId}
                      highlightClauseId={highlightClauseId}
                    />
                  ))}
                </div>
              ))}
              {doc.ungrouped_articles.map((art) => (
                <ArticleItem
                  key={art.id}
                  article={art}
                  highlightArticleId={highlightArticleId}
                  highlightClauseId={highlightClauseId}
                />
              ))}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Tab: Quan hệ văn bản */}
        <TabsContent value="relations" className="flex-1 overflow-hidden m-0">
          <ScrollArea className="h-full">
            <div className="p-4 space-y-2">
              {doc.relations.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center pt-8">
                  Không có quan hệ văn bản nào
                </p>
              ) : (
                doc.relations.map((rel, i) => (
                  <button
                    key={i}
                    onClick={() => onNavigateDoc?.(rel.doc_id)}
                    className="w-full text-left p-3 rounded-md border border-border hover:border-primary/40 hover:bg-primary/5 transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[10px] shrink-0">
                        {RELATION_LABELS[rel.relation_type] ?? rel.relation_type}
                      </Badge>
                      <span className="text-xs font-semibold text-primary group-hover:underline truncate">
                        {rel.doc_number}
                      </span>
                      <ExternalLink className="w-3 h-3 text-muted-foreground ml-auto shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                    {rel.affected_units.length > 0 && (
                      <p className="text-[10px] text-muted-foreground mt-1.5">
                        Liên quan: {rel.affected_units.slice(0, 3).join(', ')}
                        {rel.affected_units.length > 3 && ` +${rel.affected_units.length - 3} khác`}
                      </p>
                    )}
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Tab: Đồ thị — lazy */}
        <TabsContent value="graph" className="flex-1 overflow-hidden m-0 relative">
          {graphLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-background/60 z-10">
              <div className="text-sm text-muted-foreground">Đang tải đồ thị...</div>
            </div>
          )}
          {graph && <GraphViewer data={graph} onNodeClick={onNavigateDoc} />}
          {!graph && !graphLoading && (
            <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
              Đang chuẩn bị...
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
