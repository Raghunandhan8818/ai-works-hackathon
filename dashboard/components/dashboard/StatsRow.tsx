import { ecosystemStats } from '@/lib/mock-data'

const stats = [
  {
    value: ecosystemStats.totalServices,
    label: 'SERVICES',
    color: '#111827',
    bg: '#F8F7F4',
    border: '#E8E5DF',
  },
  {
    value: ecosystemStats.pendingInterrupts,
    label: 'INTERRUPT',
    color: '#92400E',
    bg: '#FFFBEB',
    border: '#FDE68A',
  },
  {
    value: ecosystemStats.autoHealed,
    label: 'AUTO-HEALED',
    color: '#065F46',
    bg: '#ECFDF5',
    border: '#6EE7B7',
  },
  {
    value: ecosystemStats.fieldsIndexed,
    label: 'FIELDS INDEXED',
    color: '#111827',
    bg: '#F8F7F4',
    border: '#E8E5DF',
  },
]

export default function StatsRow() {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded-2xl px-6 py-5"
          style={{
            background: stat.bg,
            border: `1px solid ${stat.border}`,
          }}
        >
          <div
            className="text-7xl font-bold leading-none tabular-nums"
            style={{ fontFamily: 'var(--font-syne)', color: stat.color }}
          >
            {stat.value}
          </div>
          <div
            className="text-xs font-semibold tracking-widest uppercase mt-2"
            style={{ color: stat.color, opacity: 0.6 }}
          >
            {stat.label}
          </div>
        </div>
      ))}
    </div>
  )
}
