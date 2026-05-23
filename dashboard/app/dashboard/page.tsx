'use client'

import { useState, useCallback } from 'react'
import StatsRow from '@/components/dashboard/StatsRow'
import TopBar from '@/components/dashboard/TopBar'
import EcosystemGraph from '@/components/graph/EcosystemGraph'
import BottomExpandCard from '@/components/dashboard/BottomExpandCard'

export default function DashboardPage() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null)

  const handleNodeSelect = useCallback((id: string | null) => {
    setSelectedNode(id)
  }, [])

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Ecosystem"
        subtitle="Spring PetClinic Microservices · 6 services · Last indexed 2h ago"
      />

      <div className="flex-1 flex flex-col gap-5 p-6 overflow-hidden">
        <StatsRow />

        <div className="flex-1 min-h-0">
          <EcosystemGraph onNodeSelect={handleNodeSelect} />
        </div>
      </div>

      <BottomExpandCard nodeId={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  )
}
