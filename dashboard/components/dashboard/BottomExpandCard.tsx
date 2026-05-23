'use client'

import Link from 'next/link'
import { services } from '@/lib/mock-data'
import { prChanges } from '@/lib/mock-data'

interface BottomExpandCardProps {
  nodeId: string | null
  onClose: () => void
}

const consumerRows: Record<string, { consumer: string; field: string; status: 'healed' | 'interrupt' | 'healthy' }[]> = {
  'vets-service': [
    { consumer: 'react-frontend', field: 'ownerPhone (removed)', status: 'healed' },
    { consumer: 'api-gateway', field: 'consultationFee (units)', status: 'interrupt' },
    { consumer: 'react-frontend', field: 'petAge (type changed)', status: 'healed' },
  ],
  'api-gateway': [
    { consumer: 'react-frontend', field: 'consultationFee passthrough', status: 'interrupt' },
  ],
  'react-frontend': [
    { consumer: '—', field: 'ownerPhone null-safe', status: 'healed' },
  ],
}

const statusChip = (status: 'healed' | 'interrupt' | 'healthy') => {
  if (status === 'healed')
    return (
      <span
        className="text-xs font-semibold px-2.5 py-0.5 rounded-full"
        style={{ background: '#ECFDF5', color: '#065F46', border: '1px solid #6EE7B7' }}
      >
        Auto-healed
      </span>
    )
  if (status === 'interrupt')
    return (
      <span
        className="text-xs font-semibold px-2.5 py-0.5 rounded-full"
        style={{ background: '#FFFBEB', color: '#92400E', border: '1px solid #FDE68A' }}
      >
        Interrupt
      </span>
    )
  return (
    <span
      className="text-xs font-semibold px-2.5 py-0.5 rounded-full"
      style={{ background: '#F3F4F6', color: '#374151' }}
    >
      Healthy
    </span>
  )
}

export default function BottomExpandCard({ nodeId, onClose }: BottomExpandCardProps) {
  if (!nodeId) return null

  const service = services.find((s) => s.id === nodeId)
  if (!service) return null

  const rows = consumerRows[nodeId] ?? []
  const isBreaking = service.status === 'breaking'
  const isInterrupt = service.status === 'interrupt'

  const statusBadgeStyle =
    isBreaking
      ? { bg: '#FEF2F2', text: '#9B1C1C', border: '#FECACA' }
      : isInterrupt
        ? { bg: '#FFFBEB', text: '#92400E', border: '#FDE68A' }
        : service.status === 'healed'
          ? { bg: '#ECFDF5', text: '#065F46', border: '#6EE7B7' }
          : { bg: '#F0FDF4', text: '#065F46', border: '#86EFAC' }

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
            <span
              className="font-mono text-base font-bold"
              style={{ color: '#111827' }}
            >
              {service.name}
            </span>
            <span
              className="text-xs font-semibold px-2.5 py-1 rounded-full"
              style={{
                background: statusBadgeStyle.bg,
                color: statusBadgeStyle.text,
                border: `1px solid ${statusBadgeStyle.border}`,
              }}
            >
              {service.status}
            </span>
            <span className="text-xs" style={{ color: '#6B7280' }}>
              {(isBreaking || isInterrupt) ? 'Triggered by vets-service PR #42 · 2h ago' : 'Last updated 2h ago'}
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
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
          {/* Changed fields */}
          {(isBreaking || isInterrupt) && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#6B7280' }}>
                Fields changed in PR #42
              </p>
              <div className="space-y-2">
                {prChanges.map((ch) => (
                  <div
                    key={ch.field}
                    className="flex items-center gap-3 px-4 py-2.5 rounded-xl"
                    style={{
                      background: ch.type === 'breaking' ? '#FEF2F2' : ch.type === 'interrupt' ? '#FFFBEB' : '#F8F7F4',
                      border: `1px solid ${ch.type === 'breaking' ? '#FECACA' : ch.type === 'interrupt' ? '#FDE68A' : '#E8E5DF'}`,
                    }}
                  >
                    <code
                      className="text-xs font-bold"
                      style={{ color: ch.type === 'breaking' ? '#9B1C1C' : ch.type === 'interrupt' ? '#92400E' : '#374151' }}
                    >
                      {ch.field}
                    </code>
                    <span className="text-xs" style={{ color: '#6B7280' }}>{ch.change}</span>
                    <span
                      className="ml-auto text-xs font-semibold px-2 py-0.5 rounded-full"
                      style={{
                        background: ch.type === 'breaking' ? '#FEF2F2' : ch.type === 'interrupt' ? '#FFFBEB' : '#F0FDF4',
                        color: ch.type === 'breaking' ? '#9B1C1C' : ch.type === 'interrupt' ? '#92400E' : '#065F46',
                        border: `1px solid ${ch.type === 'breaking' ? '#FECACA' : ch.type === 'interrupt' ? '#FDE68A' : '#6EE7B7'}`,
                      }}
                    >
                      {ch.type}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Consumer status */}
          {rows.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#6B7280' }}>
                Consumer status
              </p>
              <div className="space-y-2">
                {rows.map((row, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between px-4 py-2.5 rounded-xl"
                    style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
                  >
                    <div className="flex items-center gap-3">
                      <code className="text-xs font-bold" style={{ color: '#111827' }}>
                        {row.consumer}
                      </code>
                      <span className="text-xs" style={{ color: '#6B7280' }}>
                        {row.field}
                      </span>
                    </div>
                    {statusChip(row.status)}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              style={{ color: '#111827', border: '1px solid #E8E5DF', background: '#F8F7F4' }}
            >
              View PR on GitHub ↗
            </a>
            {isInterrupt && (
              <Link
                href="/dashboard/interrupts"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: '#F59E0B', color: '#FFFFFF' }}
              >
                Answer interrupt →
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
