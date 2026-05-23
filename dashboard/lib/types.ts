export type ServiceStatus = 'healthy' | 'breaking' | 'interrupt' | 'healed'

export interface Service {
  id: string
  name: string
  status: ServiceStatus
  language: string
  description: string
}

export interface GraphNode {
  id: string
  serviceId: string
  label: string
  status: ServiceStatus
  position: { x: number; y: number }
  hasInterrupt?: boolean
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  edgeType: 'healthy' | 'breaking' | 'healed' | 'registry'
  label?: string
}

export type InterruptOption = {
  id: string
  label: string
  description: string
}

export interface Interrupt {
  id: string
  service: string
  field: string
  question: string
  context: string
  options: InterruptOption[]
  sourcePR: string
  sourcePRNumber: number
  createdAt: string
  timeAgo: string
}

export type ActivityEventType =
  | 'analyzed'
  | 'auto_healed'
  | 'fix_pr_raised'
  | 'interrupt_created'
  | 'indexed'

export interface ActivityEvent {
  id: string
  type: ActivityEventType
  title: string
  service: string
  prNumber?: number
  field?: string
  timeAgo: string
  timestamp: string
}

export type FieldStatus = 'stable' | 'breaking' | 'changed'

export interface Field {
  id: string
  name: string
  type: string
  service: string
  consumers: number
  status: FieldStatus
  lastChanged: string
}
