'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

const HEAL_SEQUENCE = [
  { label: 'vets-service', status: 'breaking', msg: 'PR #42 opened — 3 contract changes detected' },
  { label: 'react-frontend', status: 'healing', msg: 'ownerPhone removed — analyzing consumers...' },
  { label: 'react-frontend', status: 'healed', msg: 'Auto-heal PR #18 raised — null-safe access applied' },
  { label: 'api-gateway', status: 'interrupt', msg: 'consultationFee units changed — needs your input' },
  { label: 'api-gateway', status: 'resolved', msg: 'Answer provided — fix PR being generated...' },
]

function HealCard() {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setStep((s) => (s + 1) % HEAL_SEQUENCE.length)
    }, 2200)
    return () => clearInterval(timer)
  }, [])

  const current = HEAL_SEQUENCE[step]

  const statusColor = {
    breaking: '#EF4444',
    healing: '#F59E0B',
    healed: '#22C55E',
    interrupt: '#F59E0B',
    resolved: '#22C55E',
  }[current.status]

  const statusLabel = {
    breaking: 'BREAKING',
    healing: 'ANALYZING',
    healed: 'HEALED',
    interrupt: 'INTERRUPT',
    resolved: 'RESOLVED',
  }[current.status]

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        minWidth: 340,
        maxWidth: 420,
      }}
    >
      {/* Header */}
      <div
        className="px-5 py-3 flex items-center gap-2"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(0,0,0,0.2)' }}
      >
        <div className="flex gap-1.5">
          <div className="w-3 h-3 rounded-full bg-red-500 opacity-70" />
          <div className="w-3 h-3 rounded-full bg-yellow-500 opacity-70" />
          <div className="w-3 h-3 rounded-full bg-green-500 opacity-70" />
        </div>
        <span className="text-xs ml-2" style={{ color: '#94A3B8', fontFamily: 'var(--font-geist-mono)' }}>
          ripple — ecosystem monitor
        </span>
      </div>

      {/* Services */}
      <div className="p-5 space-y-2.5">
        {[
          { id: 'vets-service', isActive: current.label === 'vets-service' },
          { id: 'api-gateway', isActive: current.label === 'api-gateway' },
          { id: 'react-frontend', isActive: current.label === 'react-frontend' },
        ].map(({ id, isActive }) => (
          <div
            key={id}
            className="flex items-center justify-between px-3 py-2.5 rounded-lg transition-all duration-500"
            style={{
              background: isActive ? 'rgba(255,90,31,0.08)' : 'rgba(255,255,255,0.02)',
              border: isActive
                ? `1px solid ${statusColor}33`
                : '1px solid rgba(255,255,255,0.04)',
            }}
          >
            <div className="flex items-center gap-2.5">
              <div
                className="w-2 h-2 rounded-full"
                style={{
                  background:
                    isActive
                      ? statusColor
                      : id === 'vets-service'
                        ? '#EF4444'
                        : '#22C55E',
                  boxShadow: isActive ? `0 0 8px ${statusColor}` : 'none',
                }}
              />
              <span
                className="text-sm font-mono"
                style={{ color: '#F0EDE8', fontFamily: 'var(--font-geist-mono)' }}
              >
                {id}
              </span>
            </div>
            {isActive && (
              <span
                className="text-xs font-bold px-2 py-0.5 rounded"
                style={{ color: statusColor, background: `${statusColor}18` }}
              >
                {statusLabel}
              </span>
            )}
          </div>
        ))}

        {/* Log line */}
        <div
          className="mt-4 px-3 py-2.5 rounded-lg text-xs"
          style={{
            background: 'rgba(0,0,0,0.3)',
            color: '#94A3B8',
            fontFamily: 'var(--font-geist-mono)',
            minHeight: 42,
          }}
        >
          <span style={{ color: '#FF5A1F' }}>ripple</span>
          <span style={{ color: '#94A3B8', opacity: 0.5 }}> » </span>
          <span style={{ color: '#F0EDE8' }}>{current.msg}</span>
        </div>
      </div>
    </div>
  )
}

export default function Hero() {
  return (
    <section
      className="relative min-h-screen flex items-center overflow-hidden"
      style={{ background: '#07090F' }}
    >
      {/* Background mesh gradient */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(ellipse 80% 60% at 50% -10%, rgba(255,90,31,0.12) 0%, transparent 60%), radial-gradient(ellipse 40% 40% at 80% 60%, rgba(34,197,94,0.05) 0%, transparent 50%)',
        }}
      />

      <div className="relative z-10 max-w-7xl mx-auto px-6 pt-28 pb-20 w-full">
        <div className="flex flex-col lg:flex-row items-center gap-16 lg:gap-24">
          {/* Left: copy */}
          <div className="flex-1 max-w-2xl">
            {/* Badge */}
            <div
              className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium mb-8"
              style={{
                background: 'rgba(255,90,31,0.1)',
                border: '1px solid rgba(255,90,31,0.3)',
                color: '#FF5A1F',
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF5A1F] animate-pulse" />
              Now in beta — Join 200+ engineering teams
            </div>

            {/* Headline */}
            <h1
              className="text-6xl lg:text-7xl font-bold leading-[1.05] tracking-tight mb-6"
              style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
            >
              Your microservices
              <br />
              <span style={{ color: '#FF5A1F' }}>heal themselves.</span>
            </h1>

            {/* Sub */}
            <p className="text-lg leading-relaxed mb-10 max-w-xl" style={{ color: '#94A3B8' }}>
              Ripple watches every contract between your services. When a producer changes,
              consumers are auto-healed — or asked one precise question. Silent breaks become
              closed loops.
            </p>

            {/* CTAs */}
            <div className="flex flex-wrap items-center gap-4 mb-8">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-base transition-all duration-200"
                style={{ background: '#FF5A1F', color: '#FFFFFF' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = '#e84d15'
                  e.currentTarget.style.transform = 'translateY(-1px)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = '#FF5A1F'
                  e.currentTarget.style.transform = 'translateY(0)'
                }}
              >
                Install GitHub App
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                  <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
              <button
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium text-base transition-all duration-200"
                style={{
                  color: '#F0EDE8',
                  border: '1px solid rgba(255,255,255,0.12)',
                  background: 'transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                  <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M6.5 5.5l4 2.5-4 2.5V5.5z" fill="currentColor" />
                </svg>
                Watch 5-min demo
              </button>
            </div>

            <p className="text-sm" style={{ color: '#94A3B8', opacity: 0.7 }}>
              Works with your existing GitHub workflow. No agents to manage.
            </p>
          </div>

          {/* Right: heal animation card */}
          <div className="flex-shrink-0">
            <HealCard />
          </div>
        </div>
      </div>

      {/* Bottom fade */}
      <div
        className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
        style={{
          background: 'linear-gradient(to bottom, transparent, #07090F)',
        }}
      />
    </section>
  )
}
