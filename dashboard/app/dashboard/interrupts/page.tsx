import TopBar from '@/components/dashboard/TopBar'
import InterruptCard from '@/components/interrupts/InterruptCard'
import { api, ApiDisagreement } from '@/lib/api'
import { Interrupt } from '@/lib/types'

function injectConsumerNames(options: Interrupt['options'], consumerNames: string[]): Interrupt['options'] {
  if (consumerNames.length === 0) return options
  const label = consumerNames.join(' and ')
  return options.map((o) => ({
    ...o,
    description: o.description
      .replace(/all known consumers/gi, label)
      .replace(/all consumers/gi, label),
  }))
}

function timeAgo(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function extractFieldName(fqn: string): string {
  const segments = fqn.split('::')
  const lastSegment = segments[segments.length - 1] ?? fqn
  if (lastSegment.includes('.')) {
    const fieldPart = lastSegment.split('.').pop() ?? lastSegment
    if (/^\d+$/.test(fieldPart)) {
      const endpoint = segments[2] ?? lastSegment
      return endpoint.replace(/^(GET|POST|PUT|DELETE|PATCH)\s+\/?/, '')
    }
    return fieldPart
  }
  return lastSegment.replace(/^(GET|POST|PUT|DELETE|PATCH)\s+\/?/, '')
}

function toInterrupt(d: ApiDisagreement): Interrupt {
  const fieldName = extractFieldName(d.field_fqn)
  const producerService = d.field_fqn.split('::')[0] ?? 'producer'

  const kindLabel: Record<string, string> = {
    NULLABLE_CONFLICT: 'nullable contract',
    TYPE_MISMATCH: 'type mismatch',
    FIELD_REMOVED: 'field removal',
    FIELD_RENAMED: 'field rename',
    SEMANTIC_UNIT_CHANGE: 'semantic unit change',
  }
  const kindDesc = kindLabel[d.kind] ?? d.kind.toLowerCase().replace(/_/g, ' ')

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
    field_fqn: d.field_fqn,
    consumer_service: d.consumer_service,
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

function basePath(fqn: string): string {
  const segment = fqn.split('::')[2] ?? ''
  const m = segment.match(/^(GET|POST|PUT|DELETE|PATCH)\s+\/?([^/\s?(]+)/)
  if (m) return `${m[1]}:/${m[2]}`
  return fqn
}

function groupRelatedInterrupts(interrupts: Interrupt[]): Interrupt[] {
  const result: Interrupt[] = []
  const used = new Set<string>()

  for (const primary of interrupts) {
    if (used.has(primary.id)) continue
    used.add(primary.id)

    const primaryPath = basePath(primary.field_fqn)
    const primaryTime = new Date(primary.createdAt).getTime()
    const related: Array<{ field_fqn: string; consumer_service: string; field: string; explanation: string }> = []

    for (const other of interrupts) {
      if (used.has(other.id)) continue
      const sameService = other.consumer_service === primary.consumer_service
      const withinSameRun = Math.abs(new Date(other.createdAt).getTime() - primaryTime) < 120_000
      const sameEndpoint = basePath(other.field_fqn) === primaryPath
      if (sameService && withinSameRun && sameEndpoint) {
        related.push({
          field_fqn: other.field_fqn,
          consumer_service: other.consumer_service,
          field: other.field,
          explanation: other.context,
        })
        used.add(other.id)
      }
    }

    result.push(related.length > 0 ? { ...primary, relatedFqns: related } : primary)
  }

  return result
}

export default async function InterruptsPage() {
  let interrupts: Interrupt[] = []
  let resolvedDisagreements: Awaited<ReturnType<typeof api.allDisagreements>> = []

  try {
    const [activeDisagreements, allDisagreements, services] = await Promise.all([
      api.disagreements(),
      api.allDisagreements(),
      api.services(),
    ])
    const consumerNames = services
      .filter((s) => s.role === 'consumer' || s.role === 'both')
      .map((s) => s.name)

    interrupts = groupRelatedInterrupts(
      activeDisagreements
        .filter((d) => d.resolved_at === null && d.requires_human_decision === true)
        .sort((a, b) => {
          const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
          return (order[a.severity] ?? 3) - (order[b.severity] ?? 3)
        })
        .map((d) => {
          const interrupt = toInterrupt(d)
          return { ...interrupt, options: injectConsumerNames(interrupt.options, consumerNames) }
        })
    )

    resolvedDisagreements = allDisagreements
      .filter((d) => d.resolved_at !== null)
      .sort((a, b) => new Date(b.resolved_at!).getTime() - new Date(a.resolved_at!).getTime())
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
              style={{
                background: 'var(--status-interrupt-bg)',
                color: 'var(--status-interrupt-text)',
                border: '1px solid var(--status-interrupt-text)',
              }}
            >
              {interrupts.length} awaiting your decision
            </span>
            <span className="text-sm" style={{ color: 'var(--dash-text-secondary)' }}>
              {interrupts.length > 0
                ? `These ${interrupts.length} unresolved disagreement${interrupts.length !== 1 ? 's' : ''} need your attention.`
                : '90% of fixes are applied silently. No unresolved interrupts right now.'}
            </span>
          </div>
        </div>

        {interrupts.length === 0 ? (
          <div
            className="max-w-3xl rounded-2xl px-6 py-10 flex flex-col items-center gap-3"
            style={{ background: 'var(--dash-card)', border: '1px solid var(--dash-border)' }}
          >
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center"
              style={{ background: 'var(--status-healthy-bg)', color: 'var(--status-healthy-text)' }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M4 10l4.5 4.5 7.5-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="text-sm font-semibold" style={{ color: 'var(--dash-text)' }}>All clear</p>
            <p className="text-xs text-center" style={{ color: 'var(--dash-text-secondary)' }}>
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

        {/* Resolved section */}
        {resolvedDisagreements.length > 0 && (
          <div className="max-w-3xl mt-10">
            <div className="flex items-center gap-3 mb-4">
              <div className="h-px flex-1" style={{ background: 'var(--dash-border)' }} />
              <span className="text-xs font-semibold tracking-widest uppercase" style={{ color: 'var(--dash-text-secondary)' }}>
                Resolved <span className="ml-1 px-1.5 py-0.5 rounded-full text-xs font-bold"
                  style={{ background: 'var(--dash-bg)', color: 'var(--dash-text-secondary)' }}>
                  {resolvedDisagreements.length}
                </span>
              </span>
              <div className="h-px flex-1" style={{ background: 'var(--dash-border)' }} />
            </div>
            <div className="space-y-1.5">
              {resolvedDisagreements.map((d) => {
                const fieldName = extractFieldName(d.field_fqn)
                const hasPR = d.fix_pr_url && d.fix_pr_url !== ''
                const wasAutoFix = !d.requires_human_decision
                return (
                  <div
                    key={`${d.field_fqn}::${d.consumer_service}`}
                    className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
                    style={{ background: 'var(--dash-card)', border: '1px solid var(--dash-border)' }}
                  >
                    <div
                      className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                      style={{
                        background: hasPR ? 'var(--status-healthy-bg)' : 'var(--dash-bg)',
                        color: hasPR ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)',
                      }}
                    >
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                        <path d="M1.5 5l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>

                    <code className="text-xs font-semibold flex-shrink-0" style={{ color: 'var(--dash-text)', fontFamily: 'monospace' }}>
                      {fieldName}
                    </code>
                    <span className="text-xs" style={{ color: 'var(--dash-text-secondary)' }}>{d.consumer_service}</span>

                    <div className="flex-1" />

                    {hasPR ? (
                      <>
                        <span
                          className="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                          style={{ background: 'var(--status-healthy-bg)', color: 'var(--status-healthy-text)' }}
                        >
                          Fix PR raised
                        </span>
                        <a
                          href={d.fix_pr_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs font-medium underline flex-shrink-0"
                          style={{ color: '#3B82F6' }}
                        >
                          View PR →
                        </a>
                      </>
                    ) : (
                      <span
                        className="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                        style={{
                          background: wasAutoFix ? 'var(--status-breaking-bg)' : 'var(--dash-bg)',
                          color: wasAutoFix ? 'var(--status-breaking-text)' : 'var(--dash-text-secondary)',
                        }}
                      >
                        {wasAutoFix ? 'Fix failed' : 'No fix PR'}
                      </span>
                    )}

                    <span className="text-xs flex-shrink-0" style={{ color: 'var(--dash-text-secondary)' }}>
                      {timeAgo(d.resolved_at!)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
