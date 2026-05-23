const stats = [
  {
    value: '30 sec',
    label: 'Average time to detect a contract break',
  },
  {
    value: '91%',
    label: 'Fixes applied automatically, no human input',
  },
  {
    value: '0',
    label: 'Silent production breaks since deploy',
  },
]

export default function StatsStrip() {
  return (
    <section
      className="py-20"
      style={{
        background: '#07090F',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div className="max-w-7xl mx-auto px-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 md:gap-8">
          {stats.map((stat, i) => (
            <div
              key={i}
              className="text-center md:text-left"
              style={{
                borderLeft: i > 0 ? '1px solid rgba(255,255,255,0.06)' : 'none',
                paddingLeft: i > 0 ? '2rem' : undefined,
              }}
            >
              <div
                className="text-7xl font-bold leading-none mb-3 tabular-nums"
                style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
              >
                {stat.value}
              </div>
              <div className="text-sm leading-relaxed" style={{ color: '#94A3B8', maxWidth: 200 }}>
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
