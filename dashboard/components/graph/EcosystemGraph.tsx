'use client'

import { useCallback, useEffect } from 'react'
import ReactFlow, {
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  NodeTypes,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import ServiceNode from './ServiceNode'
import { GraphNode, GraphEdge } from '@/lib/types'

const nodeTypes: NodeTypes = {
  service: ServiceNode,
}

function buildNodes(rawNodes: GraphNode[]): Node[] {
  return rawNodes.map((n) => ({
    id: n.id,
    type: 'service',
    position: n.position,
    data: {
      label: n.label,
      status: n.status,
      hasInterrupt: n.hasInterrupt,
    },
  }))
}

function buildEdges(rawEdges: GraphEdge[]): Edge[] {
  return rawEdges.map((e) => {
    const isBreaking = e.edgeType === 'breaking'
    const isHealed = e.edgeType === 'healed'
    const isRegistry = e.edgeType === 'registry'

    const strokeColor = isBreaking
      ? '#EF4444'
      : isHealed
        ? '#22C55E'
        : isRegistry
          ? '#94A3B8'
          : '#9CA3AF'

    const dashArray = isBreaking ? '8 4' : isRegistry ? '4 4' : undefined
    const animated = isBreaking

    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      animated,
      style: {
        stroke: strokeColor,
        strokeWidth: isBreaking ? 2 : 1.5,
        strokeDasharray: dashArray,
      },
      labelStyle: {
        fontSize: 10,
        fill: strokeColor,
        fontFamily: 'var(--font-geist-mono, monospace)',
      },
      labelBgStyle: {
        fill: 'rgba(255,255,255,0.9)',
        rx: 4,
      },
      markerEnd: isBreaking || isHealed
        ? {
            type: MarkerType.ArrowClosed,
            color: strokeColor,
            width: 16,
            height: 16,
          }
        : undefined,
    }
  })
}

interface EcosystemGraphProps {
  onNodeSelect: (nodeId: string | null) => void
  nodes?: GraphNode[]
  edges?: GraphEdge[]
}

export default function EcosystemGraph({ onNodeSelect, nodes: propNodes, edges: propEdges }: EcosystemGraphProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[])
  const [edges, setEdges, onEdgesChange] = useEdgesState([] as Edge[])

  useEffect(() => {
    if (propNodes && propNodes.length > 0) {
      setNodes(buildNodes(propNodes))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propNodes])

  useEffect(() => {
    if (propEdges && propEdges.length > 0) {
      setEdges(buildEdges(propEdges))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propEdges])

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id)
    },
    [onNodeSelect]
  )

  const onPaneClick = useCallback(() => {
    onNodeSelect(null)
  }, [onNodeSelect])

  const isLoading = !propNodes || propNodes.length === 0

  return (
    <div
      className="w-full h-full rounded-2xl overflow-hidden relative"
      style={{ border: '1px solid var(--dash-border)', background: 'var(--dash-card)' }}
    >
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--dash-card)' }}>
          <span className="text-sm font-mono" style={{ color: '#9CA3AF' }}>Loading ecosystem graph…</span>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.5}
        maxZoom={2}
        attributionPosition="bottom-right"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#E8E5DF"
        />
        <Controls
          style={{
            background: '#FFFFFF',
            border: '1px solid #E8E5DF',
            borderRadius: 8,
          }}
        />
      </ReactFlow>
    </div>
  )
}
