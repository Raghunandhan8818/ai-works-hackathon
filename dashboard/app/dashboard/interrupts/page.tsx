import TopBar from '@/components/dashboard/TopBar'
import InterruptCard from '@/components/interrupts/InterruptCard'
import { interrupts } from '@/lib/mock-data'

export default function InterruptsPage() {
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Interrupts"
        subtitle="Decisions that require your input before Ripple can act"
      />

      <div className="flex-1 overflow-y-auto p-6">
        {/* Header strip */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <span
              className="text-xs font-bold px-3 py-1.5 rounded-full"
              style={{ background: '#FFFBEB', color: '#92400E', border: '1px solid #FDE68A' }}
            >
              {interrupts.length} awaiting your decision
            </span>
            <span className="text-sm" style={{ color: '#6B7280' }}>
              90% of fixes are applied silently. These {interrupts.length} need your context.
            </span>
          </div>
        </div>

        {/* Interrupt cards */}
        <div className="max-w-3xl space-y-6">
          {interrupts.map((interrupt) => (
            <InterruptCard key={interrupt.id} interrupt={interrupt} />
          ))}
        </div>

        {/* Empty-state preview of resolved */}
        <div className="max-w-3xl mt-8">
          <p
            className="text-xs font-semibold uppercase tracking-wider mb-4"
            style={{ color: '#9CA3AF' }}
          >
            Recently resolved
          </p>
          <div
            className="rounded-2xl px-6 py-4 flex items-center gap-4"
            style={{ background: '#F8F7F4', border: '1px solid #E8E5DF' }}
          >
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: '#ECFDF5', color: '#065F46' }}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M2.5 7l3.5 3.5 5.5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium" style={{ color: '#111827' }}>
                visits-service — ownerId null-safe wrapper
              </p>
              <p className="text-xs mt-0.5" style={{ color: '#6B7280' }}>
                Resolved by you · Option A applied · Fix PR #22 raised · 1 day ago
              </p>
            </div>
            <span
              className="text-xs px-2.5 py-1 rounded-full font-semibold"
              style={{ background: '#ECFDF5', color: '#065F46' }}
            >
              Healed
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
