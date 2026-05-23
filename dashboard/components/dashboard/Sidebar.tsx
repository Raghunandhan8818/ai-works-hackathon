'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navItems = [
  {
    href: '/dashboard',
    label: 'Ecosystem',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
        <circle cx="5" cy="9" r="2" stroke="currentColor" strokeWidth="1.4" />
        <circle cx="13" cy="5" r="2" stroke="currentColor" strokeWidth="1.4" />
        <circle cx="13" cy="13" r="2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M7 9h2M11 5.5l-2 2M11 12.5l-2-2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    ),
    exact: true,
  },
  {
    href: '/dashboard/interrupts',
    label: 'Interrupts',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
        <path d="M9 2a7 7 0 100 14A7 7 0 009 2z" stroke="currentColor" strokeWidth="1.4" />
        <path d="M9 6v4M9 12v.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    ),
    badge: '1',
  },
  {
    href: '/dashboard/activity',
    label: 'Activity',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
        <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.4" />
        <path d="M9 5v4l2.5 2.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    href: '/dashboard/fields',
    label: 'Fields',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
        <ellipse cx="9" cy="5" rx="6" ry="2" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 5v4c0 1.1 2.7 2 6 2s6-.9 6-2V5" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 9v4c0 1.1 2.7 2 6 2s6-.9 6-2V9" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    href: '/dashboard/settings',
    label: 'Settings',
    icon: (
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
        <circle cx="9" cy="9" r="2.5" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M9 1v2M9 15v2M1 9h2M15 9h2M3.05 3.05l1.41 1.41M13.54 13.54l1.41 1.41M3.05 14.95l1.41-1.41M13.54 4.46l1.41-1.41"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
]

export default function Sidebar() {
  const pathname = usePathname()

  const isActive = (href: string, exact?: boolean) => {
    if (exact) return pathname === href
    return pathname.startsWith(href)
  }

  return (
    <aside
      className="fixed left-0 top-0 bottom-0 flex flex-col z-40"
      style={{
        width: 240,
        background: '#FFFFFF',
        borderRight: '1px solid #E8E5DF',
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-2.5 px-5 py-5"
        style={{ borderBottom: '1px solid #E8E5DF' }}
      >
        <svg width="26" height="26" viewBox="0 0 28 28" fill="none" aria-hidden>
          <circle cx="14" cy="14" r="13" stroke="#FF5A1F" strokeWidth="2" />
          <circle cx="14" cy="14" r="8" stroke="#FF5A1F" strokeWidth="1.5" strokeOpacity="0.5" />
          <circle cx="14" cy="14" r="3.5" fill="#FF5A1F" />
          <path d="M14 1 Q17 7, 14 14 Q11 21, 14 27" stroke="#FF5A1F" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
        </svg>
        <span
          className="text-lg font-bold"
          style={{ fontFamily: 'var(--font-syne)', color: '#111827' }}
        >
          Ripple
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {navItems.map((item) => {
          const active = isActive(item.href, item.exact)
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 group"
              style={{
                background: active ? 'rgba(255,90,31,0.08)' : 'transparent',
                color: active ? '#FF5A1F' : '#6B7280',
              }}
            >
              <span
                className="flex-shrink-0"
                style={{ color: active ? '#FF5A1F' : '#9CA3AF' }}
              >
                {item.icon}
              </span>
              <span
                className="text-sm font-medium flex-1"
                style={{ color: active ? '#FF5A1F' : '#374151' }}
              >
                {item.label}
              </span>
              {item.badge && (
                <span
                  className="text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center"
                  style={{ background: '#F59E0B', color: '#FFFFFF' }}
                >
                  {item.badge}
                </span>
              )}
            </Link>
          )
        })}
      </nav>

      {/* Bottom: org info */}
      <div
        className="px-4 py-4"
        style={{ borderTop: '1px solid #E8E5DF' }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{ background: '#FF5A1F', color: '#FFFFFF' }}
          >
            SP
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate" style={{ color: '#111827' }}>
              Spring PetClinic
            </p>
            <p className="text-xs truncate" style={{ color: '#6B7280' }}>
              6 services · GitHub
            </p>
          </div>
        </div>
      </div>
    </aside>
  )
}
