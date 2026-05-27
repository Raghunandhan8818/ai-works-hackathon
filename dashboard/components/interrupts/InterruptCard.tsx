'use client'

import { useState } from 'react'
import { Interrupt } from '@/lib/types'
import { api } from '@/lib/api'

interface InterruptCardProps {
  interrupt: Interrupt
}

export default function InterruptCard({ interrupt }: InterruptCardProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ status: string; workflow_id: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!selected || submitting) return
    const choice = interrupt.options.find((o) => o.id === selected)
    if (!choice) return

    setSubmitting(true)
    setError(null)
    try {
      const resolvePayload = {
        option_id: choice.id,
        option_label: choice.label,
        option_description: choice.description,
      }
      // Resolve primary + all grouped related interrupts in parallel
      const all = [
        api.resolveInterrupt({ field_fqn: interrupt.field_fqn, consumer_service: interrupt.consumer_service, ...resolvePayload }),
        ...(interrupt.relatedFqns ?? []).map((r) =>
          api.resolveInterrupt({ field_fqn: r.field_fqn, consumer_service: r.consumer_service, ...resolvePayload })
        ),
      ]
      const [res] = await Promise.all(all)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to submit — check backend')
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    const choice = interrupt.options.find((o) => o.id === selected)
    const isTriggered = result.status === 'fix_triggered'
    return (
      <div
        className="rounded-2xl p-5"
        style={{
          background: isTriggered ? '#ECFDF5' : '#F8F7F4',
          border: `1.5px solid ${isTriggered ? '#6EE7B7' : '#E8E5DF'}`,
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{ background: isTriggered ? '#22C55E' : '#9CA3AF', color: '#fff' }}
          >
            {isTriggered ? '✓' : '—'}
          </div>
          <div>
            <p className="text-sm font-semibold" style={{ color: isTriggered ? '#065F46' : '#374151' }}>
              {isTriggered ? `Fix PR queued for ${interrupt.service}` : `Decision logged for ${interrupt.service}`}
            </p>
            <p className="text-xs mt-0.5" style={{ color: isTriggered ? '#059669' : '#6B7280' }}>
              {choice?.label}
              {isTriggered && ' · Fix PR will appear in Activity shortly'}
            </p>
          </div>
        </div>
      </div>
    )
  }

  const actionOptions = interrupt.options.filter(
    (o) => o.id !== 'manual' && !o.label.toLowerCase().includes("i'll")
  )
  const dismissOption = interrupt.options.find(
    (o) => o.id === 'manual' || o.label.toLowerCase().includes("i'll")
  )

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: '#FFFFFF',
        border: '1.5px solid #FDE68A',
        boxShadow: '0 2px 16px rgba(245,158,11,0.10)',
      }}
    >
      {/* Header */}
      <div
        className="px-5 py-3.5 flex items-center gap-3"
        style={{ background: '#FFFBEB', borderBottom: '1px solid #FDE68A' }}
      >
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
          style={{ background: '#F59E0B', color: '#fff' }}
        >
          ?
        </div>
        <div className="flex-1 min-w-0 flex items-baseline justify-between gap-4">
          <div className="flex items-baseline gap-2 min-w-0 flex-wrap">
            <p className="text-sm font-semibold truncate" style={{ color: '#92400E' }}>
              {interrupt.service}
              <span className="font-normal" style={{ color: '#A16207' }}> · {interrupt.field}</span>
            </p>
            {interrupt.relatedFqns && interrupt.relatedFqns.length > 0 && (
              <span
                className="text-xs font-semibold px-2 py-0.5 rounded-full flex-shrink-0"
                style={{ background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A' }}
              >
                +{interrupt.relatedFqns.length} related
              </span>
            )}
          </div>
          <span className="text-xs flex-shrink-0" style={{ color: '#B45309' }}>{interrupt.timeAgo}</span>
        </div>
      </div>

      {/* Body */}
      <div className="px-5 py-4 space-y-4">

        {/* Before / After diff */}
        {(interrupt.producerSays || interrupt.consumerAssumes) && (
          <div
            className="grid grid-cols-2 gap-px rounded-xl overflow-hidden text-xs"
            style={{ border: '1px solid #E8E5DF' }}
          >
            <div className="px-3 py-2.5" style={{ background: '#FEF2F2' }}>
              <p className="font-semibold mb-1" style={{ color: '#9B1C1C' }}>Before</p>
              <p style={{ color: '#7F1D1D', lineHeight: '1.5' }}>{interrupt.consumerAssumes}</p>
            </div>
            <div className="px-3 py-2.5" style={{ background: '#ECFDF5' }}>
              <p className="font-semibold mb-1" style={{ color: '#065F46' }}>After</p>
              <p style={{ color: '#064E3B', lineHeight: '1.5' }}>{interrupt.producerSays}</p>
            </div>
          </div>
        )}

        {/* Context */}
        {interrupt.context && (
          <p className="text-sm" style={{ color: '#374151', lineHeight: '1.6' }}>
            {interrupt.context}
          </p>
        )}

        {/* Grouped related changes */}
        {interrupt.relatedFqns && interrupt.relatedFqns.length > 0 && (
          <div
            className="rounded-xl px-4 py-3 text-xs space-y-2"
            style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}
          >
            <p className="font-semibold" style={{ color: '#92400E' }}>
              Also resolves {interrupt.relatedFqns.length} related change{interrupt.relatedFqns.length > 1 ? 's' : ''} to the same endpoint:
            </p>
            {interrupt.relatedFqns.map((r) => (
              <p key={r.field_fqn} style={{ color: '#A16207', lineHeight: '1.5' }}>
                · {r.explanation || r.field}
              </p>
            ))}
          </div>
        )}

        {/* Action options — radio buttons */}
        <div className="space-y-2">
          {actionOptions.map((option) => (
            <label
              key={option.id}
              className="flex items-start gap-3 p-4 rounded-xl cursor-pointer transition-all"
              style={{
                background: selected === option.id ? '#FFFBEB' : '#F8F7F4',
                border: `1.5px solid ${selected === option.id ? '#F59E0B' : '#E8E5DF'}`,
              }}
            >
              <div className="mt-0.5 flex-shrink-0">
                <input
                  type="radio"
                  name={`interrupt-${interrupt.id}`}
                  value={option.id}
                  checked={selected === option.id}
                  onChange={() => setSelected(option.id)}
                  className="w-4 h-4 accent-amber-500"
                />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold" style={{ color: selected === option.id ? '#92400E' : '#111827' }}>
                  {option.label}
                </p>
                <p className="text-xs mt-0.5" style={{ color: '#6B7280', lineHeight: '1.5' }}>
                  {option.description}
                </p>
              </div>
            </label>
          ))}
        </div>

        {error && (
          <p className="text-xs px-3 py-2 rounded-lg" style={{ background: '#FEF2F2', color: '#9B1C1C' }}>
            {error}
          </p>
        )}

        {/* Footer: dismiss radio + CTA */}
        <div className="flex items-center justify-between pt-1">
          {dismissOption ? (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="radio"
                name={`interrupt-${interrupt.id}`}
                value={dismissOption.id}
                checked={selected === dismissOption.id}
                onChange={() => setSelected(dismissOption.id)}
                className="w-3.5 h-3.5 accent-amber-500"
              />
              <span
                className="text-xs transition-colors"
                style={{ color: selected === dismissOption.id ? '#92400E' : '#9CA3AF' }}
              >
                {dismissOption.label}
              </span>
            </label>
          ) : (
            <span />
          )}
          <button
            onClick={handleSubmit}
            disabled={!selected || submitting}
            className="px-4 py-2 rounded-xl text-sm font-semibold transition-all flex items-center gap-2"
            style={{
              background: selected && !submitting ? '#111827' : '#E8E5DF',
              color: selected && !submitting ? '#FFFFFF' : '#9CA3AF',
              cursor: selected && !submitting ? 'pointer' : 'not-allowed',
            }}
          >
            {submitting && (
              <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
              </svg>
            )}
            {submitting ? 'Submitting…' : 'Confirm & let Ripple act →'}
          </button>
        </div>
      </div>
    </div>
  )
}
