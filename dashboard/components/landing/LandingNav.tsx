'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

export default function LandingNav() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', handler)
    return () => window.removeEventListener('scroll', handler)
  }, [])

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-300"
      style={{
        background: scrolled
          ? 'rgba(7, 9, 15, 0.9)'
          : 'transparent',
        backdropFilter: scrolled ? 'blur(12px)' : 'none',
        borderBottom: scrolled
          ? '1px solid rgba(255,255,255,0.08)'
          : '1px solid transparent',
      }}
    >
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2.5">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" aria-hidden>
            <circle cx="14" cy="14" r="13" stroke="#FF5A1F" strokeWidth="2" />
            <circle cx="14" cy="14" r="8" stroke="#FF5A1F" strokeWidth="1.5" strokeOpacity="0.5" />
            <circle cx="14" cy="14" r="3.5" fill="#FF5A1F" />
            <path
              d="M14 1 Q17 7, 14 14 Q11 21, 14 27"
              stroke="#FF5A1F"
              strokeWidth="1.5"
              strokeOpacity="0.6"
              fill="none"
            />
          </svg>
          <span
            className="text-xl font-bold tracking-tight"
            style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
          >
            Ripple
          </span>
        </Link>

        {/* Links */}
        <div className="hidden md:flex items-center gap-8">
          {['Product', 'How it Works', 'Enterprise', 'Pricing', 'Blog'].map((link) => (
            <a
              key={link}
              href="#"
              className="text-sm transition-colors duration-200"
              style={{ color: '#94A3B8' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#F0EDE8')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#94A3B8')}
            >
              {link}
            </a>
          ))}
        </div>

        {/* CTAs */}
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="hidden md:block text-sm px-4 py-2 rounded-lg transition-colors duration-200"
            style={{ color: '#94A3B8', border: '1px solid rgba(255,255,255,0.12)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#F0EDE8'
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.24)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = '#94A3B8'
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.12)'
            }}
          >
            Sign in
          </Link>
          <Link
            href="/dashboard"
            className="text-sm px-4 py-2 rounded-lg font-semibold transition-all duration-200"
            style={{ background: '#FF5A1F', color: '#FFFFFF' }}
            onMouseEnter={(e) => (e.currentTarget.style.background = '#e84d15')}
            onMouseLeave={(e) => (e.currentTarget.style.background = '#FF5A1F')}
          >
            Start free
          </Link>
        </div>
      </div>
    </nav>
  )
}
