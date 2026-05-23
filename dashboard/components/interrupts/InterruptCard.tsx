'use client'

import { useState } from 'react'
import { Interrupt } from '@/lib/types'

interface InterruptCardProps {
  interrupt: Interrupt
}

export default function InterruptCard({ interrupt }: InterruptCardProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = () => {
    if (!selected) return
    setSubmitted(true)
  }

  if (submitted) {
    const choice = interrupt.options.find((o) => o.id === selected)
    return (
      <div
        className="rounded-2xl p-6"
        style={{ background: '#ECFDF5', border: '2px solid #6EE7B7' }}
      >
        <div className="flex items-center gap-3 mb-2">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
            style={{ background: '#22C55E', color: '#FFFFFF' }}
          >
            ✓
          </div>
          <div>
            <p className="font-semibold text-sm" style={{ color: '#065F46' }}>
              Answer submitted — Ripple is raising the fix PR for {interrupt.service}
            </p>
            <p className="text-xs mt-0.5" style={{ color: '#059669' }}>
              Selected: {choice?.label}
            </p>
          </div>
        </div>
        <p className="text-xs ml-11" style={{ color: '#059669' }}>
          Decision logged to audit trail · Fix PR will appear shortly in Activity
        </p>
      </div>
    )
  }

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
            Triggered by {interrupt.sourcePR} PR #{interrupt.sourcePRNumber} · semantic unit change detected ·{' '}
            {interrupt.timeAgo}
          </p>
        </div>
      </div>

      {/* Body */}
      <div className="px-6 py-5 space-y-5">
        {/* What changed */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#9CA3AF' }}>
            What changed in {interrupt.sourcePR}
          </p>
          <div
            className="flex items-center gap-4 px-4 py-3 rounded-xl"
            style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
          >
            <div
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
              style={{ background: '#FEF2F2', border: '1px solid #FECACA' }}
            >
              <code className="text-xs font-bold" style={{ color: '#9B1C1C' }}>
                {interrupt.field}
              </code>
              <span className="text-xs" style={{ color: '#B91C1C' }}>
                was cents (int)
              </span>
            </div>
            <span className="text-sm" style={{ color: '#9CA3AF' }}>→</span>
            <div
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
              style={{ background: '#ECFDF5', border: '1px solid #6EE7B7' }}
            >
              <code className="text-xs font-bold" style={{ color: '#065F46' }}>
                {interrupt.field}
              </code>
              <span className="text-xs" style={{ color: '#059669' }}>
                now dollars (decimal)
              </span>
            </div>
          </div>
        </div>

        {/* Question */}
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

        {/* Action */}
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs" style={{ color: '#9CA3AF' }}>
            react-frontend was auto-healed automatically · Decision will be logged to audit trail
          </p>
          <button
            onClick={handleSubmit}
            disabled={!selected}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
            style={{
              background: selected ? '#111827' : '#E8E5DF',
              color: selected ? '#FFFFFF' : '#9CA3AF',
              cursor: selected ? 'pointer' : 'not-allowed',
            }}
          >
            Answer &amp; let Ripple fix it →
          </button>
        </div>
      </div>
    </div>
  )
}
