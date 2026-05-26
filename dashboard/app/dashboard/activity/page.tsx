import TopBar from '@/components/dashboard/TopBar'
import { api } from '@/lib/api'

const severityColor: Record<string, string> = {
  CRITICAL: '#9B1C1C',
  HIGH:     '#92400E',
  MEDIUM:   '#374151',
  LOW:      '#065F46',
}

const severityBg: Record<string, string> = {
  CRITICAL: '#FEF2F2',
  HIGH:     '#FFFBEB',
  MEDIUM:   '#F3F4F6',
  LOW:      '#ECFDF5',
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default async function ActivityPage() {
  let disagreements: Awaited<ReturnType<typeof api.disagreements>> = []
  try {
    disagreements = await api.disagreements()
  } catch { /* backend not reachable */ }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Activity"
        subtitle="Detected disagreements and contract conflicts across all services"
      />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl">
          {disagreements.length === 0 ? (
            <div className="rounded-2xl p-8 text-center" style={{ border: '1px solid #E8E5DF', background: '#F8F7F4' }}>
              <div className="text-2xl mb-2">✅</div>
              <div className="text-sm font-medium" style={{ color: '#374151' }}>No active disagreements</div>
              <div className="text-xs mt-1" style={{ color: '#9CA3AF' }}>All consumer beliefs are aligned with producer contracts</div>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {disagreements.map((d, i) => {
                const col = severityColor[d.severity] || '#374151'
                const bg  = severityBg[d.severity]  || '#F3F4F6'
                const fieldName = d.field_fqn.split('::').pop() || d.field_fqn
                return (
                  <div key={i} className="rounded-2xl p-5" style={{ border: '1px solid #E8E5DF', background: '#FFFFFF' }}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-bold px-2 py-0.5 rounded-full" style={{ background: bg, color: col }}>
                            {d.severity}
                          </span>
                          <span className="text-xs font-semibold" style={{ color: '#6B7280' }}>{d.kind}</span>
                        </div>
                        <code className="text-sm font-bold block mb-1" style={{ color: '#111827', fontFamily: 'monospace' }}>
                          {fieldName}
                        </code>
                        <p className="text-xs" style={{ color: '#6B7280' }}>{d.explanation}</p>
                        <div className="mt-3 grid grid-cols-2 gap-3">
                          <div className="rounded-lg p-2.5" style={{ background: '#ECFDF5', border: '1px solid #D1FAE5' }}>
                            <div className="text-xs font-semibold mb-1" style={{ color: '#065F46' }}>Producer says</div>
                            <div className="text-xs" style={{ color: '#374151' }}>{d.producer_says}</div>
                          </div>
                          <div className="rounded-lg p-2.5" style={{ background: '#FEF2F2', border: '1px solid #FECACA' }}>
                            <div className="text-xs font-semibold mb-1" style={{ color: '#9B1C1C' }}>Consumer assumes</div>
                            <div className="text-xs" style={{ color: '#374151' }}>{d.consumer_assumes}</div>
                          </div>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs" style={{ color: '#9CA3AF' }}>{timeAgo(d.detected_at)}</div>
                        <code className="text-xs mt-1 block" style={{ color: '#6B7280', fontFamily: 'monospace' }}>{d.consumer_service}</code>
                        {d.fix_pr_url && (
                          <a href={d.fix_pr_url} target="_blank" rel="noreferrer"
                            className="text-xs mt-1 block underline" style={{ color: '#2563EB' }}>
                            Fix PR →
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
