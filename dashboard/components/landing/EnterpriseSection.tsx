const pillars = [
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M12 2L4 6v6c0 5.25 3.5 10.15 8 11.35C16.5 22.15 20 17.25 20 12V6l-8-4z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'Security-first architecture',
    points: [
      'Runs entirely in your network — no code leaves your infra',
      'GitHub App with minimal, scoped permissions only',
      'Full audit log: every decision, model call, and PR logged',
      'SOC 2 Type II report available on request',
    ],
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
        <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M9 12h6M12 9v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'Your models, your data',
    points: [
      'LiteLLM bridge: Claude, Gemini, GPT-4o, or any OpenAI-compat',
      'Ollama support for full air-gapped operation',
      'No training on your code — ever',
      'Model swappable per org, team, or repo',
    ],
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.5" />
        <path d="M12 7v5l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M5 12h2M17 12h2M12 5v2M12 17v2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.5" />
      </svg>
    ),
    title: 'Built to scale',
    points: [
      'Temporal-powered: durable, distributed workflow execution',
      'Parallel LLM calls across consumers — no sequential bottleneck',
      'Tested with 100+ service ecosystems',
      'Incremental re-index on merge — not full scans',
    ],
  },
]

export default function EnterpriseSection() {
  return (
    <section id="enterprise" className="py-32" style={{ background: '#07090F' }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="mb-16 text-center">
          <span
            className="text-xs font-semibold tracking-widest uppercase"
            style={{ color: '#FF5A1F' }}
          >
            Enterprise
          </span>
          <h2
            className="mt-3 text-4xl lg:text-5xl font-bold"
            style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
          >
            Built for teams that
            <br />
            <span style={{ color: '#94A3B8' }}>can&apos;t afford silent breaks.</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {pillars.map((pillar, i) => (
            <div
              key={i}
              className="p-8 rounded-2xl"
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
              }}
            >
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center mb-6"
                style={{ background: 'rgba(255,90,31,0.1)', color: '#FF5A1F' }}
              >
                {pillar.icon}
              </div>
              <h3
                className="text-lg font-bold mb-5"
                style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
              >
                {pillar.title}
              </h3>
              <ul className="space-y-3">
                {pillar.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-2.5 text-sm" style={{ color: '#94A3B8' }}>
                    <span className="mt-1 flex-shrink-0" style={{ color: '#FF5A1F' }}>—</span>
                    {pt}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
