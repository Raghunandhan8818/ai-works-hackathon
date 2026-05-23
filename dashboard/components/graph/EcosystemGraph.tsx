'use client'

import { useCallback, useMemo } from 'react'
import ReactFlow, {
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  NodeTypes,
  EdgeTypes,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import ServiceNode from './ServiceNode'
import { graphNodes, graphEdges } from '@/lib/mock-data'
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
}

export default function EcosystemGraph({ onNodeSelect }: EcosystemGraphProps) {
  const initialNodes = useMemo(() => buildNodes(graphNodes), [])
  const initialEdges = useMemo(() => buildEdges(graphEdges), [])

  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id)
    },
    [onNodeSelect]
  )

  const onPaneClick = useCallback(() => {
    onNodeSelect(null)
  }, [onNodeSelect])

  return (
    <div
      className="w-full h-full rounded-2xl overflow-hidden"
      style={{ border: '1px solid #E8E5DF', background: '#FAFAF8' }}
    >
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
