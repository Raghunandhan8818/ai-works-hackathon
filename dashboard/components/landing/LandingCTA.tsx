'use client'

import Link from 'next/link'

export default function LandingCTA() {
  return (
    <section className="py-32" style={{ background: '#07090F' }}>
      <div className="max-w-4xl mx-auto px-6 text-center">
        {/* Radial glow */}
        <div
          className="absolute left-1/2 -translate-x-1/2 w-[600px] h-[300px] pointer-events-none"
          style={{
            background: 'radial-gradient(ellipse at center, rgba(255,90,31,0.12) 0%, transparent 70%)',
            filter: 'blur(40px)',
          }}
        />

        <div className="relative">
          <span
            className="inline-flex items-center gap-2 text-xs font-semibold tracking-widest uppercase mb-8"
            style={{ color: '#FF5A1F' }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#FF5A1F] animate-pulse" />
            Now in beta
          </span>

          <h2
            className="text-5xl lg:text-6xl font-bold leading-tight mb-6"
            style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
          >
            Start healing your
            <br />
            ecosystem today.
          </h2>

          <p className="text-xl leading-relaxed mb-12 mx-auto max-w-2xl" style={{ color: '#94A3B8' }}>
            Join 200+ engineering teams who&apos;ve turned silent production breaks into
            closed loops. Install in 60 seconds — no infra changes required.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-semibold text-base transition-all duration-200"
              style={{ background: '#FF5A1F', color: '#FFFFFF' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#e84d15'
                e.currentTarget.style.transform = 'translateY(-2px)'
                e.currentTarget.style.boxShadow = '0 8px 32px rgba(255,90,31,0.35)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#FF5A1F'
                e.currentTarget.style.transform = 'translateY(0)'
                e.currentTarget.style.boxShadow = 'none'
              }}
            >
              Install GitHub App
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
            <button
              className="inline-flex items-center gap-2 px-8 py-4 rounded-xl font-medium text-base transition-all duration-200"
              style={{
                color: '#F0EDE8',
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'transparent',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.24)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'
              }}
            >
              Talk to us
            </button>
          </div>

          <p className="mt-8 text-sm" style={{ color: '#94A3B8', opacity: 0.6 }}>
            No credit card. No sales call. Works with your existing GitHub workflow.
          </p>
        </div>
      </div>
    </section>
  )
}
