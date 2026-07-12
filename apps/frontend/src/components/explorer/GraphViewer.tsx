'use client'

import { useEffect, useRef } from 'react'
import type { GraphData } from '@/types/documents'

// Node colors theo label — từ ontology contract
const NODE_COLORS: Record<string, string> = {
  Document: '#3b82f6',      // xanh dương
  Article: '#f59e0b',       // vàng
  Clause: '#f97316',        // cam
  Point: '#a78bfa',         // tím nhạt
  LegalConcept: '#8b5cf6',  // tím
  LegalSubject: '#10b981',  // xanh lá
  LegalAction: '#06b6d4',   // cyan
  Issuer: '#6b7280',        // xám
}

const LEGEND = Object.entries(NODE_COLORS).map(([label, color]) => ({ label, color }))

interface GraphViewerProps {
  data: GraphData
  onNodeClick?: (docId: string) => void
}

export default function GraphViewer({ data, onNodeClick }: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || !data.nodes.length) return

    // Import cytoscape dynamically để đảm bảo client-only
    let destroyed = false
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let cyInstance: any = null

    import('cytoscape').then(({ default: cytoscape }) => {
      if (destroyed || !containerRef.current) return

      cyInstance = cytoscape({
        container: containerRef.current,
        elements: [
          ...data.nodes.map((n) => ({
            data: {
              id: n.id,
              label: `${n.label}\n${String(n.properties?.number ?? n.properties?.name ?? '')}`,
              nodeLabel: n.label,
              ...n.properties,
            },
          })),
          ...data.edges.map((e) => ({
            data: {
              source: e.source,
              target: e.target,
              label: e.relation_type,
            },
          })),
        ],
        style: [
          {
            selector: 'node',
            style: {
              'background-color': (ele: cytoscape.NodeSingular) =>
                NODE_COLORS[ele.data('nodeLabel') as string] ?? '#9ca3af',
              label: 'data(label)',
              'font-size': '10px',
              'text-wrap': 'wrap',
              'text-max-width': '80px',
              'text-valign': 'center',
              color: '#ffffff',
              'text-outline-width': 1,
              'text-outline-color': '#00000066',
              width: 40,
              height: 40,
            },
          },
          {
            selector: 'edge',
            style: {
              label: 'data(label)',
              'font-size': '8px',
              'curve-style': 'bezier',
              'target-arrow-shape': 'triangle',
              'line-color': '#6b7280',
              'target-arrow-color': '#6b7280',
              color: '#6b7280',
              'text-background-color': '#ffffff',
              'text-background-opacity': 0.7,
              'text-background-padding': '2px',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-width': 3,
              'border-color': '#10b981',
            },
          },
        ],
        layout: { name: 'cose', animate: true, animationDuration: 400 },
        userZoomingEnabled: true,
        userPanningEnabled: true,
      })

      // Click node có label "Document" → navigate
      cyInstance.on('tap', 'node', (evt: cytoscape.EventObject) => {
        const node = evt.target
        if (node.data('nodeLabel') === 'Document' && onNodeClick) {
          onNodeClick(node.id())
        }
      })
    })

    // Cleanup khi unmount — bắt buộc tránh memory leak
    return () => {
      destroyed = true
      if (cyInstance) {
        cyInstance.destroy()
        cyInstance = null
      }
    }
  }, [data, onNodeClick])

  return (
    <div className="relative w-full h-full min-h-[400px]">
      {/* Truncation warning */}
      {data.truncated && (
        <div className="absolute top-2 left-2 z-10 text-[10px] bg-card border border-border px-2 py-1 rounded shadow-sm">
          Hiển thị {data.nodes.length}/{data.total_nodes ?? '?'} nodes ·{' '}
          {data.edges.length}/{data.total_edges ?? '?'} quan hệ
        </div>
      )}

      {/* Legend */}
      <div className="absolute top-2 right-2 z-10 bg-card border border-border rounded p-2 shadow-sm">
        {LEGEND.slice(0, 5).map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1.5 mb-0.5">
            <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
            <span className="text-[10px] text-foreground/60">{label}</span>
          </div>
        ))}
      </div>

      {/* Cytoscape container */}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  )
}
