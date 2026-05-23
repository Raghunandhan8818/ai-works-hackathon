'use client'

import Link from 'next/link'

const links = {
  Product: ['Features', 'How it Works', 'Pricing', 'Changelog'],
  Docs: ['Getting Started', 'GitHub App Setup', 'ripple.yaml Reference', 'API Reference'],
  Company: ['About', 'Blog', 'Careers', 'Security'],
  Legal: ['Privacy Policy', 'Terms of Service', 'Cookie Policy'],
}

export default function LandingFooter() {
  return (
    <footer
      className="py-16"
      style={{
        background: '#07090F',
        borderTop: '1px solid rgba(255,255,255,0.07)',
      }}
    >
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-8 mb-12">
          {/* Brand */}
          <div className="col-span-2">
            <Link href="/" className="flex items-center gap-2.5 mb-4">
              <svg width="26" height="26" viewBox="0 0 28 28" fill="none" aria-hidden>
                <circle cx="14" cy="14" r="13" stroke="#FF5A1F" strokeWidth="2" />
                <circle cx="14" cy="14" r="8" stroke="#FF5A1F" strokeWidth="1.5" strokeOpacity="0.5" />
                <circle cx="14" cy="14" r="3.5" fill="#FF5A1F" />
                <path d="M14 1 Q17 7, 14 14 Q11 21, 14 27" stroke="#FF5A1F" strokeWidth="1.5" strokeOpacity="0.6" fill="none" />
              </svg>
              <span
                className="text-lg font-bold"
                style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
              >
                Ripple
              </span>
            </Link>
            <p className="text-sm leading-relaxed" style={{ color: '#94A3B8', maxWidth: 220 }}>
              Self-healing microservice ecosystems. Silent breaks become closed loops.
            </p>
          </div>

          {/* Link columns */}
          {Object.entries(links).map(([section, items]) => (
            <div key={section}>
              <p className="text-xs font-semibold tracking-wider uppercase mb-4" style={{ color: '#F0EDE8' }}>
                {section}
              </p>
              <ul className="space-y-2.5">
                {items.map((item) => (
                  <li key={item}>
                    <a
                      href="#"
                      className="text-sm transition-colors duration-200"
                      style={{ color: '#94A3B8' }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = '#F0EDE8')}
                      onMouseLeave={(e) => (e.currentTarget.style.color = '#94A3B8')}
                    >
                      {item}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div
          className="flex flex-col sm:flex-row items-center justify-between pt-8"
          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
        >
          <p className="text-xs" style={{ color: '#94A3B8', opacity: 0.6 }}>
            © 2025 Ripple Technologies, Inc. All rights reserved.
          </p>
          <div className="flex items-center gap-6 mt-4 sm:mt-0">
            {['GitHub', 'Discord', 'Twitter'].map((social) => (
              <a
                key={social}
                href="#"
                className="text-xs transition-colors duration-200"
                style={{ color: '#94A3B8', opacity: 0.6 }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = '1'
                  e.currentTarget.style.color = '#F0EDE8'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '0.6'
                  e.currentTarget.style.color = '#94A3B8'
                }}
              >
                {social}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
