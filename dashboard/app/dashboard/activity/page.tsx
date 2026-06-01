import Link from 'next/link'
import TopBar from '@/components/dashboard/TopBar'
import { api, ApiDisagreement } from '@/lib/api'

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

const severityColor: Record<string, string> = {
  CRITICAL: 'var(--status-breaking-text)',
  HIGH:     'var(--status-interrupt-text)',
  MEDIUM:   'var(--dash-text)',
  LOW:      'var(--status-healthy-text)',
}

const severityBg: Record<string, string> = {
  CRITICAL: 'var(--status-breaking-bg)',
  HIGH:     'var(--status-interrupt-bg)',
  MEDIUM:   'var(--dash-bg)',
  LOW:      'var(--status-healthy-bg)',
}

function SectionHeader({ title, count, color }: { title: string; count: number; color: string }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-sm font-semibold" style={{ color }}>
        {title}
      </span>
      <span
        className="text-xs font-bold px-2 py-0.5 rounded-full tabular-nums"
        style={{ background: 'var(--dash-bg)', color: 'var(--dash-text-secondary)' }}
      >
        {count}
      </span>
      <div className="h-px flex-1" style={{ background: 'var(--dash-border)' }} />
    </div>
  )
}

export default async function ActivityPage() {
  let disagreements: ApiDisagreement[] = []
  try {
    disagreements = await api.allDisagreements()
  } catch { /* backend not reachable */ }

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
            <div
              className="rounded-2xl p-8 text-center"
              style={{ border: '1px solid var(--dash-border)', background: 'var(--dash-card)' }}
            >
              <div className="text-2xl mb-2">✅</div>
              <div className="text-sm font-medium" style={{ color: 'var(--dash-text)' }}>No active disagreements</div>
              <div className="text-xs mt-1" style={{ color: 'var(--dash-text-secondary)' }}>All consumer beliefs are aligned with producer contracts</div>
            </div>
          ) : (
            <div className="space-y-8">

              {/* Auto-fixes */}
              {autoFixes.length > 0 && (
                <div>
                  <SectionHeader
                    title="Ripple auto-fixes"
                    count={autoFixes.length}
                    color={autoFixes.some(d => d.fix_pr_url) ? 'var(--status-healthy-text)' : '#3B82F6'}
                  />
                  <div className="space-y-2">
                    {autoFixes.map((d, i) => {
                      const hasPR = d.fix_pr_url && d.fix_pr_url !== ''
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl"
                          style={{
                            background: 'var(--dash-card)',
                            border: `1px solid ${hasPR ? 'rgba(63,185,80,0.4)' : 'rgba(59,130,246,0.4)'}`,
                          }}
                        >
                          <div
                            className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0"
                            style={{
                              background: hasPR ? 'var(--status-healthy-bg)' : 'rgba(59,130,246,0.1)',
                              color: hasPR ? 'var(--status-healthy-text)' : '#3B82F6',
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

                          <code className="text-xs font-semibold flex-shrink-0" style={{ color: 'var(--dash-text)', fontFamily: 'monospace' }}>
                            {extractFieldName(d.field_fqn)}
                          </code>
                          <span className="text-xs" style={{ color: 'var(--dash-text-secondary)' }}>{d.consumer_service}</span>
                          <span
                            className="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                            style={{ background: severityBg[d.severity] || 'var(--dash-bg)', color: severityColor[d.severity] || 'var(--dash-text)' }}
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
                              style={{ color: '#3B82F6' }}
                            >
                              View PR →
                            </a>
                          ) : (
                            <span className="text-xs flex-shrink-0" style={{ color: 'var(--dash-text-secondary)' }}>
                              PR pending…
                            </span>
                          )}

                          <span className="text-xs flex-shrink-0" style={{ color: 'var(--dash-text-secondary)' }}>
                            {timeAgo(d.detected_at)}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Awaiting Decision */}
              {awaitingDecision.length > 0 && (
                <div>
                  <SectionHeader title="Needs your input" count={awaitingDecision.length} color="var(--status-interrupt-text)" />
                  <div className="space-y-2">
                    {awaitingDecision.map((d, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-3 px-4 py-3 rounded-xl"
                        style={{ background: 'var(--dash-card)', border: '1px solid var(--status-interrupt-text)' }}
                      >
                        <span
                          className="text-xs font-bold px-2 py-0.5 rounded-full flex-shrink-0"
                          style={{ background: severityBg[d.severity] || 'var(--dash-bg)', color: severityColor[d.severity] || 'var(--dash-text)' }}
                        >
                          {d.severity}
                        </span>
                        <code className="text-xs font-semibold flex-shrink-0" style={{ color: 'var(--dash-text)', fontFamily: 'monospace' }}>
                          {extractFieldName(d.field_fqn)}
                        </code>
                        <span className="text-xs" style={{ color: 'var(--dash-text-secondary)' }}>{d.consumer_service}</span>
                        <div className="flex-1" />
                        <Link
                          href="/dashboard/interrupts"
                          className="text-xs font-medium underline flex-shrink-0"
                          style={{ color: 'var(--status-interrupt-text)' }}
                        >
                          Go to interrupts →
                        </Link>
                        <span className="text-xs flex-shrink-0" style={{ color: 'var(--dash-text-secondary)' }}>
                          {timeAgo(d.detected_at)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Resolved */}
              {resolved.length > 0 && (
                <div>
                  <SectionHeader title="Resolved" count={resolved.length} color="var(--dash-text)" />
                  <div className="space-y-2">
                    {resolved.map((d, i) => {
                      const hasPR = d.fix_pr_url && d.fix_pr_url !== ''
                      const wasAutoFix = !d.requires_human_decision
                      return (
                        <div
                          key={i}
                          className="flex items-center gap-3 px-4 py-3 rounded-xl"
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
                            {extractFieldName(d.field_fqn)}
                          </code>
                          <span className="text-xs" style={{ color: 'var(--dash-text-secondary)' }}>{d.consumer_service}</span>

                          <div className="flex-1" />

                          {hasPR ? (
                            <a
                              href={d.fix_pr_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs font-medium underline flex-shrink-0"
                              style={{ color: '#3B82F6' }}
                            >
                              View PR →
                            </a>
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
          )}
        </div>
      </div>
    </div>
  )
}
