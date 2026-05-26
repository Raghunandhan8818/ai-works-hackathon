import TopBar from '@/components/dashboard/TopBar'
import InterruptCard from '@/components/interrupts/InterruptCard'
import { api, ApiDisagreement } from '@/lib/api'
import { Interrupt } from '@/lib/types'

function timeAgo(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function toInterrupt(d: ApiDisagreement): Interrupt {
  const fieldName = d.field_fqn.split('.').pop() ?? d.field_fqn
  const producerService = d.field_fqn.split('.')[0] ?? 'producer'

  const kindLabel: Record<string, string> = {
    NULLABLE_CONFLICT: 'nullable contract',
    TYPE_MISMATCH: 'type mismatch',
    FIELD_REMOVED: 'field removal',
    FIELD_RENAMED: 'field rename',
    SEMANTIC_UNIT_CHANGE: 'semantic unit change',
  }
  const kindDesc = kindLabel[d.kind] ?? d.kind.toLowerCase().replace(/_/g, ' ')

  // Use LLM-generated mitigation options when present.
  // Only append "I'll fix it manually" if there isn't already a manual/dismiss option.
  const hasManualOption = d.mitigation_options.some(
    (o) => o.id === 'manual' || o.label.toLowerCase().includes('manual') || o.label.toLowerCase().includes('coordinate')
  )

  const baseOptions = d.mitigation_options.length > 0
    ? d.mitigation_options.map((o) => ({ id: o.id, label: o.label, description: o.description }))
    : [
        {
          id: 'auto_fix',
          label: "Apply Ripple's automated fix",
          description: `Let Ripple raise a fix PR in ${d.consumer_service} to align with ${producerService}.`,
        },
      ]

  const options = hasManualOption
    ? baseOptions
    : [
        ...baseOptions,
        {
          id: 'manual',
          label: "I'll handle this manually",
          description: 'Dismiss. Decision logged to audit trail — no auto-fix triggered.',
        },
      ]

  return {
    id: `${d.field_fqn}::${d.consumer_service}`,
    service: d.consumer_service,
    field: fieldName,
    question: d.requires_human_decision && d.human_decision_reason
      ? d.human_decision_reason
      : `How should ${d.consumer_service} handle the ${kindDesc} in "${fieldName}"?`,
    context: d.explanation,
    options,
    sourcePR: producerService,
    producerSays: d.producer_says,
    consumerAssumes: d.consumer_assumes,
    createdAt: d.detected_at,
    timeAgo: timeAgo(d.detected_at),
  }
}

export default async function InterruptsPage() {
  let interrupts: Interrupt[] = []

  try {
    const disagreements = await api.disagreements()
    interrupts = disagreements
      .filter((d) => d.resolved_at === null && d.requires_human_decision === true)
      .sort((a, b) => {
        const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
        return (order[a.severity] ?? 3) - (order[b.severity] ?? 3)
      })
      .map(toInterrupt)
  } catch {
    // backend unavailable — show empty state
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Interrupts"
        subtitle="Decisions that require your input before Ripple can act"
      />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <span
              className="text-xs font-bold px-3 py-1.5 rounded-full"
              style={{ background: '#FFFBEB', color: '#92400E', border: '1px solid #FDE68A' }}
            >
              {interrupts.length} awaiting your decision
            </span>
            <span className="text-sm" style={{ color: '#6B7280' }}>
              {interrupts.length > 0
                ? `These ${interrupts.length} unresolved disagreement${interrupts.length !== 1 ? 's' : ''} need your attention.`
                : '90% of fixes are applied silently. No unresolved interrupts right now.'}
            </span>
          </div>
        </div>

        {interrupts.length === 0 ? (
          <div
            className="max-w-3xl rounded-2xl px-6 py-10 flex flex-col items-center gap-3"
            style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
          >
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center"
              style={{ background: '#ECFDF5', color: '#065F46' }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M4 10l4.5 4.5 7.5-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-sm font-semibold" style={{ color: '#111827' }}>All clear</p>
            <p className="text-xs text-center" style={{ color: '#6B7280' }}>
              No unresolved disagreements require your input. Ripple is handling everything automatically.
            </p>
          </div>
        ) : (
          <div className="max-w-3xl space-y-6">
            {interrupts.map((interrupt) => (
              <InterruptCard key={interrupt.id} interrupt={interrupt} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
