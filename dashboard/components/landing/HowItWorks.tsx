export default function HowItWorks() {
  const steps = [
    {
      number: '01',
      title: 'Install',
      description:
        'Install the Ripple GitHub App in under 60 seconds. Ripple adds a ripple.yaml to your repo — that\'s your ecosystem config. No infra changes required.',
      detail: 'GitHub App · ripple.yaml · Zero-config start',
    },
    {
      number: '02',
      title: 'Index',
      description:
        'Ripple maps every field contract between your services using SCIP-powered static analysis. It builds a live Knowledge Graph of producer fields and consumer beliefs.',
      detail: 'SCIP indexer · Field graph · Consumer beliefs',
    },
    {
      number: '03',
      title: 'Break detected',
      description:
        'A producer opens a PR. Within 30 seconds, Ripple posts a bot comment listing every affected consumer, the exact fields impacted, and whether each can be auto-healed.',
      detail: '30s detection · Bot comment · Impact list',
    },
    {
      number: '04',
      title: 'Heals',
      description:
        'Mechanical breaks (renamed fields, null-safety) get a silent fix PR. Semantic breaks (unit changes, business logic) get one precise interrupt card — one question, then a PR.',
      detail: 'Silent PR · Interrupt card · Audit trail',
    },
  ]

  return (
    <section id="how-it-works" className="relative py-32" style={{ background: '#07090F' }}>
      <div className="max-w-7xl mx-auto px-6">
        {/* Section label */}
        <div className="mb-16">
          <span
            className="text-xs font-semibold tracking-widest uppercase"
            style={{ color: '#FF5A1F' }}
          >
            How It Works
          </span>
          <h2
            className="mt-3 text-4xl lg:text-5xl font-bold leading-tight"
            style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
          >
            From PR to healed
            <br />
            <span style={{ color: '#94A3B8' }}>in four steps.</span>
          </h2>
        </div>

        {/* Steps */}
        <div className="relative">
          {/* Connector line (desktop) */}
          <div
            className="hidden lg:block absolute top-8 left-0 right-0 h-px"
            style={{ background: 'linear-gradient(to right, transparent, rgba(255,90,31,0.3), rgba(255,90,31,0.3), transparent)' }}
          />

          <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 lg:gap-6">
            {steps.map((step, i) => (
              <div key={step.number} className="relative">
                {/* Step number bubble */}
                <div
                  className="w-16 h-16 rounded-full flex items-center justify-center mb-6 relative z-10"
                  style={{
                    background: i === 0 ? '#FF5A1F' : 'rgba(255,255,255,0.04)',
                    border: i === 0 ? 'none' : '1px solid rgba(255,90,31,0.3)',
                  }}
                >
                  <span
                    className="text-lg font-bold"
                    style={{
                      fontFamily: 'var(--font-syne)',
                      color: i === 0 ? '#FFFFFF' : '#FF5A1F',
                    }}
                  >
                    {step.number}
                  </span>
                </div>

                <h3
                  className="text-xl font-bold mb-3"
                  style={{ fontFamily: 'var(--font-syne)', color: '#F0EDE8' }}
                >
                  {step.title}
                </h3>
                <p className="text-sm leading-relaxed mb-4" style={{ color: '#94A3B8' }}>
                  {step.description}
                </p>
                <p className="text-xs font-mono" style={{ color: 'rgba(255,90,31,0.7)' }}>
                  {step.detail}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
