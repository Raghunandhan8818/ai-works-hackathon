import Link from 'next/link'
import TopBar from '@/components/dashboard/TopBar'
import { api, ApiDisagreement } from '@/lib/api'

const severityColor: Record<string, string> = {
  CRITICAL: '#9B1C1C',
  HIGH:     '#92400E',
  MEDIUM:   '#374151',
  LOW:      '#065F46',
}

const severityBg: Record<string, string> = {
  CRITICAL: '#FEF2F2',
  HIGH:     '#FFFBEB',
  MEDIUM:   '#F3F4F6',
  LOW:      '#ECFDF5',
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
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

function SectionHeader({ title, count, color }: { title: string; count: number; color: string }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-sm font-semibold" style={{ color }}>
        {title}
      </span>
      <span
        className="text-xs font-bold px-2 py-0.5 rounded-full tabular-nums"
        style={{ background: '#F3F4F6', color: '#374151' }}
      >
        {count}
      </span>
      <div className="h-px flex-1" style={{ background: '#E8E5DF' }} />
    </div>
  )
}

export default async function ActivityPage() {
  let disagreements: ApiDisagreement[] = []
  try {
    disagreements = await api.allDisagreements()
  } catch { /* backend not reachable */ }

  // All auto-fix items (unresolved, not requiring human decision) — PR link shown when available
  const autoFixes = disagreements.filter(
    (d) => !d.requires_human_decision && d.resolved_at === null
  )
  const awaitingDecision = disagreements.filter(
    (d) => d.requires_human_decision && d.resolved_at === null
  )
  const resolved = disagreements
    .filter((d) => d.resolved_at !== null)
    .sort((a, b) => new Date(b.resolved_at!).getTime() - new Date(a.resolved_at!).getTime())

  const isEmpty = disagreements.length === 0

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Activity"
        subtitle="Auto-fixed PRs, pending decisions, and resolved disagreements"
      />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl">
          {isEmpty ? (
            <div className="rounded-2xl p-8 text-center" style={{ border: '1px solid #E8E5DF', background: '#F8F7F4' }}>
              <div className="text-2xl mb-2">✅</div>
              <div className="text-sm font-medium" style={{ color: '#374151' }}>No active disagreements</div>
              <div className="text-xs mt-1" style={{ color: '#9CA3AF' }}>All consumer beliefs are aligned with producer contracts</div>
            </div>
          ) : (
            <div className="space-y-8">

              {/* Section 1: Auto-fixes (PR link shown once raised, spinner while pending) */}
              {autoFixes.length > 0 && (
                <div>
                  <SectionHeader
                    title="Ripple auto-fixes"
                    count={autoFixes.length}
                    color={autoFixes.some(d => d.fix_pr_url) ? '#065F46' : '#1D4ED8'}
                  />
                  <div className="space-y-2">
                    {autoFixes.map((d, i) => {
                      const hasPR = d.fix_pr_url && d.fix_pr_url !== ''
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl"
                          style={{
                            background: '#FFFFFF',
                            border: `1px solid ${hasPR ? '#D1FAE5' : '#BFDBFE'}`,
                          }}
                        >
                          {/* Status icon */}
                          <div
                            className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                            style={{
                              background: hasPR ? '#ECFDF5' : '#EFF6FF',
                              color: hasPR ? '#059669' : '#2563EB',
                            }}
                          >
                            {hasPR ? (
                              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                                <path d="M1.5 5l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            ) : (
                              <svg className="animate-spin" width="10" height="10" viewBox="0 0 10 10" fill="none">
                                <path d="M5 1a4 4 0 1 1 0 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                              </svg>
                            )}
                          </div>

                          <code className="text-xs font-semibold flex-shrink-0" style={{ color: '#111827', fontFamily: 'monospace' }}>
                            {extractFieldName(d.field_fqn)}
                          </code>
                          <span className="text-xs" style={{ color: '#6B7280' }}>{d.consumer_service}</span>
                          <span
                            className="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                            style={{ background: severityBg[d.severity] || '#F3F4F6', color: severityColor[d.severity] || '#374151' }}
                          >
                            {d.severity}
                          </span>

                          <div className="flex-1" />

                          {hasPR ? (
                            <a
                              href={d.fix_pr_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs font-medium underline flex-shrink-0"
                              style={{ color: '#2563EB' }}
                            >
                              View PR →
                            </a>
                          ) : (
                            <span className="text-xs flex-shrink-0" style={{ color: '#6B7280' }}>
                              PR pending…
                            </span>
                          )}

                          <span className="text-xs flex-shrink-0" style={{ color: '#9CA3AF' }}>
                            {timeAgo(d.detected_at)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Section 2: Awaiting Decision */}
              {awaitingDecision.length > 0 && (
                <div>
                  <SectionHeader title="Needs your input" count={awaitingDecision.length} color="#92400E" />
                  <div className="space-y-2">
                    {awaitingDecision.map((d, i) => {
                      const col = severityColor[d.severity] || '#374151'
                      const bg  = severityBg[d.severity]  || '#F3F4F6'
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl"
                          style={{ background: '#FFFFFF', border: '1px solid #FDE68A' }}
                        >
                          <span
                            className="text-xs font-bold px-2 py-0.5 rounded-full flex-shrink-0"
                            style={{ background: bg, color: col }}
                          >
                            {d.severity}
                          </span>
                          <code className="text-xs font-semibold flex-shrink-0" style={{ color: '#111827', fontFamily: 'monospace' }}>
                            {extractFieldName(d.field_fqn)}
                          </code>
                          <span className="text-xs" style={{ color: '#6B7280' }}>{d.consumer_service}</span>
                          <div className="flex-1" />
                          <Link
                            href="/dashboard/interrupts"
                            className="text-xs font-medium underline flex-shrink-0"
                            style={{ color: '#92400E' }}
                          >
                            Go to interrupts →
                          </Link>
                          <span className="text-xs flex-shrink-0" style={{ color: '#9CA3AF' }}>
                            {timeAgo(d.detected_at)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Section 3: Resolved */}
              {resolved.length > 0 && (
                <div>
                  <SectionHeader title="Resolved" count={resolved.length} color="#374151" />
                  <div className="space-y-2">
                    {resolved.map((d, i) => {
                      const hasPR = d.fix_pr_url && d.fix_pr_url !== ''
                      const wasAutoFix = !d.requires_human_decision
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl"
                          style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
                        >
                          {/* Icon */}
                          <div
                            className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                            style={{
                              background: hasPR ? '#ECFDF5' : '#F3F4F6',
                              color: hasPR ? '#059669' : '#9CA3AF',
                            }}
                          >
                            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                              <path d="M1.5 5l2.5 2.5 4.5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          </div>

                          <code className="text-xs font-semibold flex-shrink-0" style={{ color: '#111827', fontFamily: 'monospace' }}>
                            {extractFieldName(d.field_fqn)}
                          </code>
                          <span className="text-xs" style={{ color: '#6B7280' }}>{d.consumer_service}</span>

                          <div className="flex-1" />

                          {/* PR link or status label */}
                          {hasPR ? (
                            <a
                              href={d.fix_pr_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs font-medium underline flex-shrink-0"
                              style={{ color: '#2563EB' }}
                            >
                              View PR →
                            </a>
                          ) : (
                            <span
                              className="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                              style={{
                                background: wasAutoFix ? '#FEF2F2' : '#F3F4F6',
                                color: wasAutoFix ? '#9B1C1C' : '#6B7280',
                              }}
                            >
                              {wasAutoFix ? 'Fix failed' : 'No fix PR'}
                            </span>
                          )}

                          <span className="text-xs flex-shrink-0" style={{ color: '#9CA3AF' }}>
                            {timeAgo(d.resolved_at!)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

            </div>
          )}
        </div>
      </div>
    </div>
  )
}
