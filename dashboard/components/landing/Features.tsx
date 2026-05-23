'use client'

const features = [
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path d="M10 2L3 6v8l7 4 7-4V6l-7-4z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M10 10l7-4M10 10v8M10 10L3 6" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: 'Auto-Healing Consumer PRs',
    description:
      'When a field rename or null-safety issue is detected, Ripple opens a fix PR on every affected consumer — automatically, silently, without any human input. Mechanical changes just disappear.',
    tag: 'Mechanical breaks',
    tagColor: '#22C55E',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10 6v4l3 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'Semantic Interrupt Cards',
    description:
      'For changes that require business context — unit changes, format shifts, semantic renames — Ripple asks exactly one question. You answer, Ripple generates the fix PR. No back-and-forth.',
    tag: 'Semantic breaks',
    tagColor: '#F59E0B',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <circle cx="5" cy="10" r="2" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="15" cy="5" r="2" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="15" cy="15" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 10h4M13 6.5l-2 2M13 13.5l-2-2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'Ecosystem Knowledge Graph',
    description:
      'Every field contract, every consumer belief, indexed continuously. Visualize your entire microservice ecosystem as a live graph — see exactly who depends on what before you merge.',
    tag: 'SCIP-powered',
    tagColor: '#94A3B8',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path d="M3 3h14v10H3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M7 17h6M10 13v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M6 7l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'Production Incident Loop',
    description:
      'Jira tickets, PagerDuty alerts, or Slack messages become Ripple tasks. RCA surfaces the root field contract. Fix is proposed, tested, and merged — all tracked in the audit log.',
    tag: 'Jira · PagerDuty',
    tagColor: '#94A3B8',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <rect x="3" y="5" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7 10h6M10 7v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'Local Model Support',
    description:
      'Bring your own model via LiteLLM. Ripple works with Ollama, Claude, Gemini, GPT-4o, and any OpenAI-compatible endpoint. Run fully air-gapped for compliance-sensitive teams.',
    tag: 'LiteLLM · Ollama',
    tagColor: '#94A3B8',
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
        <path d="M10 2v4M10 14v4M2 10h4M14 10h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="10" cy="10" r="3" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
    title: 'Full Audit Trail',
    description:
      'Every decision, every PR, every LLM call is logged with full context. Know exactly why Ripple chose auto-heal vs interrupt. Export to your SIEM or compliance tooling.',
    tag: 'SOC 2 ready',
    tagColor: '#94A3B8',
  },
]

export default function Features() {
  return (
    <section id="product" className="py-32" style={{ background: '#07090F' }}>
      <div className="max-w-7xl mx-auto px-6">
        <div className="mb-16">
          <span
            className="text-xs font-semibold tracking-widest uppercase"
            style={{ color: '#FF5A1F' }}
          >
            Features
          </span>
          <h2
            className="mt-3 text-4xl lg:text-5xl font-bold"
            style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
          >
            Everything your ecosystem
            <br />
            <span style={{ color: '#94A3B8' }}>needs to self-heal.</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((f, i) => (
            <div
              key={i}
              className="p-6 rounded-2xl transition-all duration-300 group"
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.07)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.05)'
                e.currentTarget.style.borderColor = 'rgba(255,90,31,0.2)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
                e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)'
              }}
            >
              <div
                className="w-10 h-10 rounded-xl flex items-center justify-center mb-4"
                style={{ background: 'rgba(255,90,31,0.1)', color: '#FF5A1F' }}
              >
                {f.icon}
              </div>
              <h3
                className="text-lg font-semibold mb-2"
                style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
              >
                {f.title}
              </h3>
              <p className="text-sm leading-relaxed mb-4" style={{ color: '#94A3B8' }}>
                {f.description}
              </p>
              <span
                className="inline-flex items-center text-xs font-medium px-2.5 py-1 rounded-full"
                style={{
                  background: `${f.tagColor}15`,
                  color: f.tagColor,
                  border: `1px solid ${f.tagColor}30`,
                }}
              >
                {f.tag}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
