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
  activeDisagreements: ApiDisagreement[],   // unresolved only — drives edge colour
  allDisagreements: ApiDisagreement[],       // full history — drives topology
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  // Build relationship map from ALL disagreements (including resolved) so edges
  // survive even when everything is healthy / resolved.
  const pairMap = new Map<string, number>()
  const producerSet = new Set<string>()
  const consumerSet = new Set<string>()

  for (const d of allDisagreements) {
    const producer = d.field_fqn.split('::')[0]
    const consumer = d.consumer_service
    if (!producer || producer === consumer) continue
    producerSet.add(producer)
    consumerSet.add(consumer)
    const key = `${producer}→${consumer}`
    pairMap.set(key, (pairMap.get(key) ?? 0) + 1)
  }

  // Augment sets from service roles
  for (const s of services) {
    if (s.role === 'producer' || s.role === 'both') producerSet.add(s.name)
    if (s.role === 'consumer' || s.role === 'both') consumerSet.add(s.name)
  }

  // Ensure every known producer is connected to every known consumer as a healthy
  // baseline — fills gaps when disagreements were attributed differently or don't exist yet.
  for (const producer of producerSet) {
    for (const consumer of consumerSet) {
      if (producer === consumer) continue
      const key = `${producer}→${consumer}`
      if (!pairMap.has(key)) pairMap.set(key, 0)
    }
  }

  // Active (unresolved) disagreements determine edge colour and node status
  const activeBreakingConsumers = new Set(activeDisagreements.map((d) => d.consumer_service))
  const activePairs = new Set(
    activeDisagreements.map((d) => `${d.field_fqn.split('::')[0]}→${d.consumer_service}`)
  )

  const pureProducers = services.filter((s) => producerSet.has(s.name) && !consumerSet.has(s.name))
  const pureConsumers = services.filter((s) => consumerSet.has(s.name) && !producerSet.has(s.name))
  const both = services.filter((s) => producerSet.has(s.name) && consumerSet.has(s.name))
  const neither = services.filter((s) => !producerSet.has(s.name) && !consumerSet.has(s.name))

  // Centre groups vertically so nodes spread nicely rather than stacking at y=80
  const centredY = (i: number, total: number, canvasH = 500) => {
    if (total === 1) return canvasH / 2
    const spacing = Math.min(180, (canvasH - 80) / (total - 1))
    const groupH = (total - 1) * spacing
    return (canvasH - groupH) / 2 + i * spacing
  }

  const seenNodes = new Set<string>()
  const nodes: GraphNode[] = []

  const addNode = (s: ApiService, x: number, i: number, total: number) => {
    if (seenNodes.has(s.name)) return
    seenNodes.add(s.name)
    nodes.push({
      id: s.name,
      serviceId: s.name,
      label: s.name,
      status: activeBreakingConsumers.has(s.name) ? 'breaking' : 'healthy',
      position: { x, y: centredY(i, total) },
    })
  }

  pureProducers.forEach((s, i) => addNode(s, 80,  i, pureProducers.length))
  both.forEach((s, i)          => addNode(s, 340, i, both.length))
  pureConsumers.forEach((s, i) => addNode(s, 600, i, pureConsumers.length))
  neither.forEach((s, i)       => addNode(s, 340, both.length + i, both.length + neither.length))

  const edges: GraphEdge[] = []
  for (const [key] of pairMap) {
    const [producer, consumer] = key.split('→')
    if (!seenNodes.has(producer) || !seenNodes.has(consumer)) continue
    const isBreaking = activePairs.has(key)
    edges.push({
      id: `${producer}-${consumer}`,
      source: producer,
      target: consumer,
      edgeType: isBreaking ? 'breaking' : 'healthy',
    })
  }

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
    Promise.all([api.services(), api.disagreements(), api.allDisagreements()])
      .then(([services, activeDisagreements, allDisagreements]) => {
        setApiServices(services)
        setApiDisagreements(activeDisagreements)
        const { nodes, edges } = buildGraph(services, activeDisagreements, allDisagreements)
        setGraphNodes(nodes)
        setGraphEdges(edges)
        const totalFields = services.reduce((s, svc) => s + svc.field_count, 0)
        setSubtitle(
          `${services.length} services · ${totalFields} fields indexed · ${allDisagreements.length} disagreements`
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
