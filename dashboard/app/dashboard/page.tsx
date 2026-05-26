'use client'

import { useState, useCallback, useEffect } from 'react'
import StatsRow from '@/components/dashboard/StatsRow'
import TopBar from '@/components/dashboard/TopBar'
import EcosystemGraph from '@/components/graph/EcosystemGraph'
import BottomExpandCard from '@/components/dashboard/BottomExpandCard'
import { api, ApiService, ApiDisagreement } from '@/lib/api'
import { GraphNode, GraphEdge } from '@/lib/types'


function buildGraph(
  services: ApiService[],
  disagreements: ApiDisagreement[]
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const producers = services.filter((s) => s.role === 'producer' || s.role === 'both')
  const consumers = services.filter((s) => s.role === 'consumer' || s.role === 'both')

  const breakingConsumers = new Set(disagreements.map((d) => d.consumer_service))

  // Position: producers on left column, consumers on right
  const nodes: GraphNode[] = []
  producers.forEach((s, i) => {
    nodes.push({
      id: s.name,
      serviceId: s.name,
      label: s.name,
      status: breakingConsumers.has(s.name) ? 'breaking' : 'healthy',
      position: { x: 100, y: 100 + i * 180 },
    })
  })
  consumers.forEach((s, i) => {
    nodes.push({
      id: s.name,
      serviceId: s.name,
      label: s.name,
      status: breakingConsumers.has(s.name) ? 'breaking' : 'healthy',
      position: { x: 500, y: 100 + i * 180 },
    })
  })

  // Edges: producer → consumer for each pair
  const edges: GraphEdge[] = []
  producers.forEach((p) => {
    consumers.forEach((c) => {
      const hasBreaking = disagreements.some((d) => d.consumer_service === c.name)
      edges.push({
        id: `${p.name}-${c.name}`,
        source: p.name,
        target: c.name,
        edgeType: hasBreaking ? 'breaking' : 'healthy',
        label: hasBreaking ? `${disagreements.filter((d) => d.consumer_service === c.name).length} disagreement(s)` : undefined,
      })
    })
  })

  return { nodes, edges }
}

export default function DashboardPage() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([])
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([])
  const [apiServices, setApiServices] = useState<ApiService[]>([])
  const [apiDisagreements, setApiDisagreements] = useState<ApiDisagreement[]>([])
  const [subtitle, setSubtitle] = useState('Loading…')

  useEffect(() => {
    Promise.all([api.services(), api.disagreements()])
      .then(([services, disagreements]) => {
        setApiServices(services)
        setApiDisagreements(disagreements)
        const { nodes, edges } = buildGraph(services, disagreements)
        setGraphNodes(nodes)
        setGraphEdges(edges)
        setSubtitle(
          `${services.length} services · ${services.reduce((s, svc) => s + svc.field_count, 0)} fields indexed · ${disagreements.length} disagreements`
        )
      })
      .catch(() => setSubtitle('Backend unavailable'))
  }, [])

  const handleNodeSelect = useCallback((id: string | null) => {
    setSelectedNode(id)
  }, [])

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar title="Ecosystem" subtitle={subtitle} />

      <div className="flex-1 flex flex-col gap-5 p-6 overflow-hidden">
        <StatsRow />

        <div className="flex-1 min-h-0">
          <EcosystemGraph
            onNodeSelect={handleNodeSelect}
            nodes={graphNodes}
            edges={graphEdges}
          />
        </div>
      </div>

      <BottomExpandCard
        nodeId={selectedNode}
        onClose={() => setSelectedNode(null)}
        services={apiServices}
        disagreements={apiDisagreements}
      />
    </div>
  )
}
