export default function GitHubBotPreview() {
  return (
    <section className="py-32" style={{ background: '#07090F' }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
          {/* Copy */}
          <div>
            <span
              className="text-xs font-semibold tracking-widest uppercase"
              style={{ color: '#FF5A1F' }}
            >
              GitHub Native
            </span>
            <h2
              className="mt-3 text-4xl font-bold leading-tight mb-6"
              style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
            >
              The PR comment
              <br />that does the work.
            </h2>
            <p className="text-lg leading-relaxed mb-8" style={{ color: '#94A3B8' }}>
              When a producer PR opens, Ripple posts a single structured comment. Every
              affected consumer, every changed field, and what Ripple is doing about each
              one — in your normal GitHub review flow.
            </p>
            <ul className="space-y-3">
              {[
                'Posted within 30 seconds of PR open',
                'Links directly to auto-heal PRs',
                'Interrupt cards open inline',
                'Updates as fixes land',
              ].map((item) => (
                <li key={item} className="flex items-center gap-3 text-sm" style={{ color: '#94A3B8' }}>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
                    <circle cx="8" cy="8" r="7" stroke="#22C55E" strokeWidth="1.2" />
                    <path d="M5 8l2 2 4-4" stroke="#22C55E" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {item}
                </li>
              ))}
            </ul>
          </div>

          {/* GitHub comment mockup */}
          <div
            className="rounded-2xl overflow-hidden"
            style={{
              background: '#0D1117',
              border: '1px solid rgba(255,255,255,0.08)',
              fontFamily: 'var(--font-geist-mono)',
            }}
          >
            {/* Comment header */}
            <div
              className="flex items-center gap-3 px-5 py-3.5"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}
            >
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
                style={{ background: '#FF5A1F', color: '#FFFFFF' }}
              >
                R
              </div>
              <div>
                <span className="text-sm font-semibold" style={{ color: '#F0EDE8' }}>ripple-bot</span>
                <span className="text-xs ml-2" style={{ color: '#6B7280' }}>commented 28 seconds ago</span>
              </div>
              <div
                className="ml-auto text-xs px-2 py-0.5 rounded"
                style={{ background: 'rgba(255,90,31,0.15)', color: '#FF5A1F', border: '1px solid rgba(255,90,31,0.3)' }}
              >
                Bot
              </div>
            </div>

            {/* Comment body */}
            <div className="p-5 space-y-4">
              <div>
                <p className="text-base font-semibold mb-1" style={{ color: '#F0EDE8', fontFamily: 'inherit' }}>
                  🌊 Ripple — 2 consumers affected by vets-service PR #42
                </p>
                <p className="text-xs" style={{ color: '#6B7280' }}>
                  3 field changes detected · 1 auto-healed · 1 needs your input
                </p>
              </div>

              {/* Table */}
              <div
                className="rounded-xl overflow-hidden text-xs"
                style={{ border: '1px solid rgba(255,255,255,0.06)' }}
              >
                <table className="w-full">
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
                      <th className="text-left px-4 py-2.5 font-medium" style={{ color: '#94A3B8' }}>Consumer</th>
                      <th className="text-left px-4 py-2.5 font-medium" style={{ color: '#94A3B8' }}>Field</th>
                      <th className="text-left px-4 py-2.5 font-medium" style={{ color: '#94A3B8' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                      <td className="px-4 py-3" style={{ color: '#F0EDE8' }}>react-frontend</td>
                      <td className="px-4 py-3" style={{ color: '#94A3B8' }}>ownerPhone (removed)</td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium"
                          style={{ background: 'rgba(34,197,94,0.1)', color: '#22C55E', border: '1px solid rgba(34,197,94,0.2)' }}
                        >
                          ✓ Auto-healed · PR #18
                        </span>
                      </td>
                    </tr>
                    <tr style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                      <td className="px-4 py-3" style={{ color: '#F0EDE8' }}>api-gateway</td>
                      <td className="px-4 py-3" style={{ color: '#94A3B8' }}>consultationFee (units)</td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium"
                          style={{ background: 'rgba(245,158,11,0.1)', color: '#F59E0B', border: '1px solid rgba(245,158,11,0.2)' }}
                        >
                          ⚠ Your input needed
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Action */}
              <div
                className="flex items-center justify-between px-4 py-3 rounded-xl"
                style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.15)' }}
              >
                <div className="text-xs" style={{ color: '#94A3B8' }}>
                  <span style={{ color: '#F59E0B' }}>api-gateway</span> needs your decision on consultationFee units
                </div>
                <button
                  className="text-xs font-semibold px-3 py-1.5 rounded-lg"
                  style={{ background: '#F59E0B', color: '#000000' }}
                >
                  Answer →
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
