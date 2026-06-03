const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8081'

export interface ApiService {
  name: string
  repo_url: string
  language: string
  role: string
  field_count: number
  consumer_count: number
  last_indexed_at: string | null
}

export interface ApiField {
  fqn: string
  name: string
  producer_service: string
  transport: string
  endpoint_or_topic: string
  field_path: string
  declared_type: string
  nullable: boolean
  deprecated: boolean
  constraints: { kind: string; value: string }[]
}

export interface MitigationOption {
  id: string
  label: string
  description: string
}

export interface ApiDisagreement {
  field_fqn: string
  consumer_service: string
  kind: string
  producer_says: string
  consumer_assumes: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  explanation: string
  detected_at: string
  resolved_at: string | null
  fix_pr_url: string
  requires_human_decision: boolean
  human_decision_reason: string
  mitigation_options: MitigationOption[]
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { next: { revalidate: 10 } })
  if (!res.ok) throw new Error(`${path} → ${res.status}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${path} → ${res.status}`)
  return res.json()
}

export const api = {
  services: () => get<ApiService[]>('/services'),
  fields: (service?: string) =>
    get<ApiField[]>(service ? `/fields?service=${encodeURIComponent(service)}` : '/fields'),
  disagreements: (fieldFqn?: string) =>
    get<ApiDisagreement[]>(
      fieldFqn ? `/disagreements?field_fqn=${encodeURIComponent(fieldFqn)}` : '/disagreements'
    ),
  allDisagreements: () => get<ApiDisagreement[]>('/disagreements/all'),
  resolveInterrupt: (payload: {
    field_fqn: string
    consumer_service: string
    option_id: string
    option_label: string
    option_description: string
  }) => post<{ status: string; workflow_id: string | null }>('/api/interrupt/resolve', payload),
  getReviewEnabled: () =>
    get<{ architectural_review_enabled: boolean }>('/api/settings/review-enabled'),
  setReviewEnabled: (enabled: boolean) =>
    post<{ architectural_review_enabled: boolean }>('/api/settings/review-enabled', { enabled }),
}
