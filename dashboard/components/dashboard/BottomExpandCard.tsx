'use client'

import Link from 'next/link'
import { ApiService, ApiDisagreement } from '@/lib/api'

interface BottomExpandCardProps {
  nodeId: string | null
  onClose: () => void
  services: ApiService[]
  disagreements: ApiDisagreement[]
}

const severityChip = (severity: string) => {
  const styles: Record<string, { bg: string; text: string; border: string }> = {
    CRITICAL: { bg: '#FEF2F2', text: '#9B1C1C', border: '#FECACA' },
    HIGH:     { bg: '#FFFBEB', text: '#92400E', border: '#FDE68A' },
    MEDIUM:   { bg: '#FFF7ED', text: '#9A3412', border: '#FDBA74' },
    LOW:      { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' },
  }
  const s = styles[severity] ?? styles.LOW
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}
    >
      {severity}
    </span>
  )
}

const kindLabel = (kind: string) =>
  kind.toLowerCase().replace(/_/g, ' ')

export default function BottomExpandCard({ nodeId, onClose, services, disagreements }: BottomExpandCardProps) {
  if (!nodeId) return null

  const service = services.find((s) => s.name === nodeId)

  const asConsumer = disagreements.filter(
    (d) => d.consumer_service === nodeId && d.resolved_at === null
  )
  const asProducer = disagreements.filter(
    (d) => d.field_fqn.split('.')[0] === nodeId && d.resolved_at === null
  )

  const hasIssues = asConsumer.length > 0 || asProducer.length > 0
  const statusLabel = hasIssues ? 'breaking' : 'healthy'
  const statusStyle = hasIssues
    ? { bg: '#FEF2F2', text: '#9B1C1C', border: '#FECACA' }
    : { bg: '#ECFDF5', text: '#065F46', border: '#6EE7B7' }

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex justify-center pointer-events-none"
      style={{ paddingLeft: 240, paddingBottom: 0 }}
    >
      <div
        className="pointer-events-auto w-full max-w-3xl rounded-t-2xl animate-slide-up"
        style={{
          background: '#FFFFFF',
          border: '1px solid #E8E5DF',
          borderBottom: 'none',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.12)',
          maxHeight: '60vh',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 sticky top-0"
          style={{ background: '#FFFFFF', borderBottom: '1px solid #E8E5DF' }}
        >
          <div className="flex items-center gap-3">
            <span className="font-mono text-base font-bold" style={{ color: '#111827' }}>
              {nodeId}
            </span>
            <span
              className="text-xs font-semibold px-2.5 py-1 rounded-full"
              style={{
                background: statusStyle.bg,
                color: statusStyle.text,
                border: `1px solid ${statusStyle.border}`,
              }}
            >
              {statusLabel}
            </span>
            {service && (
              <span className="text-xs" style={{ color: '#6B7280' }}>
                {service.language} · {service.role} · {service.field_count} fields
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ color: '#6B7280', background: '#F3F4F6' }}
            aria-label="Close"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          {/* Disagreements as consumer */}
          {asConsumer.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#6B7280' }}>
                Active disagreements — consuming {asConsumer.length} broken field{asConsumer.length !== 1 ? 's' : ''}
              </p>
              <div className="space-y-2">
                {asConsumer.map((d, i) => {
                  const fieldName = d.field_fqn.split('.').pop() ?? d.field_fqn
                  const producer = d.field_fqn.split('.')[0]
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
                      style={{ background: '#FEF2F2', border: '1px solid #FECACA' }}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-xs font-bold" style={{ color: '#9B1C1C' }}>{fieldName}</code>
                          <span className="text-xs" style={{ color: '#6B7280' }}>from {producer}</span>
                          <span className="text-xs" style={{ color: '#9B1C1C' }}>· {kindLabel(d.kind)}</span>
                        </div>
                        <p className="text-xs mt-0.5 truncate" style={{ color: '#6B7280' }}>{d.explanation}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {severityChip(d.severity)}
                        {d.fix_pr_url && (
                          <a
                            href={d.fix_pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-medium px-2 py-0.5 rounded-full"
                            style={{ background: '#ECFDF5', color: '#065F46', border: '1px solid #6EE7B7' }}
                          >
                            Fix PR ↗
                          </a>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Disagreements as producer */}
          {asProducer.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#6B7280' }}>
                Downstream impact — {asProducer.length} consumer{asProducer.length !== 1 ? 's' : ''} affected
              </p>
              <div className="space-y-2">
                {asProducer.map((d, i) => {
                  const fieldName = d.field_fqn.split('.').pop() ?? d.field_fqn
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
                      style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-xs font-bold" style={{ color: '#92400E' }}>{fieldName}</code>
                          <span className="text-xs" style={{ color: '#6B7280' }}>→ {d.consumer_service}</span>
                          <span className="text-xs" style={{ color: '#92400E' }}>· {kindLabel(d.kind)}</span>
                        </div>
                        <p className="text-xs mt-0.5 truncate" style={{ color: '#6B7280' }}>{d.explanation}</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {severityChip(d.severity)}
                        {d.fix_pr_url && (
                          <a
                            href={d.fix_pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-medium px-2 py-0.5 rounded-full"
                            style={{ background: '#ECFDF5', color: '#065F46', border: '1px solid #6EE7B7' }}
                          >
                            Fix PR ↗
                          </a>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Healthy state */}
          {!hasIssues && (
            <div
              className="flex items-center gap-3 px-4 py-3 rounded-xl"
              style={{ background: '#ECFDF5', border: '1px solid #6EE7B7' }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8l3.5 3.5 6.5-7" stroke="#065F46" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-sm font-medium" style={{ color: '#065F46' }}>
                No active disagreements — this service is healthy
              </span>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-1">
            {asConsumer.length > 0 && (
              <Link
                href="/dashboard/interrupts"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: '#F59E0B', color: '#FFFFFF' }}
              >
                View interrupts →
              </Link>
            )}
            {service?.repo_url && (
              <a
                href={service.repo_url.replace('.git', '')}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium"
                style={{ color: '#111827', border: '1px solid #E8E5DF', background: '#F8F7F4' }}
              >
                View repo ↗
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
