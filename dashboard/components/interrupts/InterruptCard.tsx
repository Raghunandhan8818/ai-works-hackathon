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

    // Parse field_fqn and consumer_service out of the interrupt id
    const [field_fqn, consumer_service] = interrupt.id.split('::')

    setSubmitting(true)
    setError(null)
    try {
      const res = await api.resolveInterrupt({
        field_fqn,
        consumer_service,
        option_id: choice.id,
        option_label: choice.label,
        option_description: choice.description,
      })
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
        className="rounded-2xl p-6"
        style={{
          background: isTriggered ? '#ECFDF5' : '#F8F7F4',
          border: `2px solid ${isTriggered ? '#6EE7B7' : '#E8E5DF'}`,
        }}
      >
        <div className="flex items-center gap-3 mb-2">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
            style={{ background: isTriggered ? '#22C55E' : '#6B7280', color: '#FFFFFF' }}
          >
            {isTriggered ? '✓' : '—'}
          </div>
          <div>
            <p className="font-semibold text-sm" style={{ color: isTriggered ? '#065F46' : '#374151' }}>
              {isTriggered
                ? `Fix PR being raised for ${interrupt.service}`
                : `Decision logged for ${interrupt.service}`}
            </p>
            <p className="text-xs mt-0.5" style={{ color: isTriggered ? '#059669' : '#6B7280' }}>
              Selected: {choice?.label}
            </p>
          </div>
        </div>
        {isTriggered && (
          <p className="text-xs ml-11" style={{ color: '#059669' }}>
            Ripple is cloning the consumer repo and applying your chosen strategy · Fix PR will appear in Activity shortly
          </p>
        )}
      </div>
    )
  }

  const selectedChoice = interrupt.options.find((o) => o.id === selected)

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: '#FFFFFF',
        border: '2px solid #FDE68A',
        boxShadow: '0 4px 24px rgba(245,158,11,0.12)',
      }}
    >
      {/* Header */}
      <div
        className="px-6 py-4 flex items-start gap-4"
        style={{ background: '#FFFBEB', borderBottom: '1px solid #FDE68A' }}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-base flex-shrink-0 mt-0.5"
          style={{ background: '#F59E0B', color: '#FFFFFF' }}
        >
          ?
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-bold text-sm" style={{ color: '#92400E', fontFamily: 'var(--font-syne)' }}>
            Ripple needs your input — {interrupt.service}
          </p>
          <p className="text-xs mt-0.5" style={{ color: '#A16207' }}>
            Triggered by {interrupt.sourcePR}{interrupt.sourcePRNumber ? ` PR #${interrupt.sourcePRNumber}` : ''} · semantic contract change detected · {interrupt.timeAgo}
          </p>
        </div>
      </div>

      {/* Body */}
      <div className="px-6 py-5 space-y-5">
        {/* What changed — real producer_says vs consumer_assumes */}
        {(interrupt.producerSays || interrupt.consumerAssumes) && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#9CA3AF' }}>
              Contract conflict on <code className="font-mono">{interrupt.field}</code>
            </p>
            <div
              className="flex items-center gap-4 px-4 py-3 rounded-xl flex-wrap"
              style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
            >
              {interrupt.consumerAssumes && (
                <div
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
                  style={{ background: '#FEF2F2', border: '1px solid #FECACA' }}
                >
                  <span className="text-xs font-semibold" style={{ color: '#9B1C1C' }}>Consumer assumed</span>
                  <code className="text-xs font-bold" style={{ color: '#9B1C1C' }}>
                    {interrupt.consumerAssumes.length > 60
                      ? interrupt.consumerAssumes.slice(0, 60) + '…'
                      : interrupt.consumerAssumes}
                  </code>
                </div>
              )}
              <span className="text-sm" style={{ color: '#9CA3AF' }}>→</span>
              {interrupt.producerSays && (
                <div
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
                  style={{ background: '#ECFDF5', border: '1px solid #6EE7B7' }}
                >
                  <span className="text-xs font-semibold" style={{ color: '#065F46' }}>Producer now says</span>
                  <code className="text-xs font-bold" style={{ color: '#065F46' }}>
                    {interrupt.producerSays.length > 60
                      ? interrupt.producerSays.slice(0, 60) + '…'
                      : interrupt.producerSays}
                  </code>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Question + context */}
        <div>
          <p className="text-base font-bold mb-1" style={{ color: '#111827', fontFamily: 'var(--font-syne)' }}>
            {interrupt.question}
          </p>
          <p className="text-sm" style={{ color: '#6B7280' }}>
            {interrupt.context}
          </p>
        </div>

        {/* Options */}
        <div className="space-y-2.5">
          {interrupt.options.map((option) => (
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
                <p
                  className="text-sm font-semibold"
                  style={{ color: selected === option.id ? '#92400E' : '#111827' }}
                >
                  {option.label}
                </p>
                <p className="text-xs mt-0.5" style={{ color: '#6B7280' }}>
                  {option.description}
                </p>
              </div>
            </label>
          ))}
        </div>

        {error && (
          <p className="text-xs font-medium px-3 py-2 rounded-lg" style={{ background: '#FEF2F2', color: '#9B1C1C' }}>
            {error}
          </p>
        )}

        {/* Action */}
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs" style={{ color: '#9CA3AF' }}>
            {selected === 'manual'
              ? 'Decision logged to audit trail — no auto-fix will be triggered'
              : selected
                ? 'Ripple will apply this strategy and raise a fix PR'
                : 'Select an option above'}
          </p>
          <button
            onClick={handleSubmit}
            disabled={!selected || submitting}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all flex items-center gap-2"
            style={{
              background: selected && !submitting ? '#111827' : '#E8E5DF',
              color: selected && !submitting ? '#FFFFFF' : '#9CA3AF',
              cursor: selected && !submitting ? 'pointer' : 'not-allowed',
            }}
          >
            {submitting && (
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
              </svg>
            )}
            {submitting ? 'Submitting…' : 'Answer & let Ripple act →'}
          </button>
        </div>
      </div>
    </div>
  )
}
