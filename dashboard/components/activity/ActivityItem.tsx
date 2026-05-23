import { ActivityEvent, ActivityEventType } from '@/lib/types'

const typeConfig: Record<
  ActivityEventType,
  { label: string; iconBg: string; iconColor: string; chipBg: string; chipText: string }
> = {
  analyzed: {
    label: 'PR Analyzed',
    iconBg: '#EFF6FF',
    iconColor: '#1D4ED8',
    chipBg: '#EFF6FF',
    chipText: '#1E40AF',
  },
  auto_healed: {
    label: 'Auto-Healed',
    iconBg: '#ECFDF5',
    iconColor: '#059669',
    chipBg: '#ECFDF5',
    chipText: '#065F46',
  },
  fix_pr_raised: {
    label: 'Fix PR Raised',
    iconBg: '#ECFDF5',
    iconColor: '#059669',
    chipBg: '#ECFDF5',
    chipText: '#065F46',
  },
  interrupt_created: {
    label: 'Interrupt',
    iconBg: '#FFFBEB',
    iconColor: '#D97706',
    chipBg: '#FFFBEB',
    chipText: '#92400E',
  },
  indexed: {
    label: 'Indexed',
    iconBg: '#F3F4F6',
    iconColor: '#6B7280',
    chipBg: '#F3F4F6',
    chipText: '#374151',
  },
}

const TypeIcon = ({ type }: { type: ActivityEventType }) => {
  if (type === 'analyzed')
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M7 1a6 6 0 100 12A6 6 0 007 1z" stroke="currentColor" strokeWidth="1.3" />
        <path d="M4.5 7l2 2L9.5 5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  if (type === 'auto_healed' || type === 'fix_pr_raised')
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M2.5 7l3 3 6-6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  if (type === 'interrupt_created')
    return (
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M7 1a6 6 0 100 12A6 6 0 007 1z" stroke="currentColor" strokeWidth="1.3" />
        <path d="M7 4.5v4M7 9.5v.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    )
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M7 1v6M7 9.5v.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
}

interface ActivityItemProps {
  event: ActivityEvent
  isLast?: boolean
}

export default function ActivityItem({ event, isLast }: ActivityItemProps) {
  const config = typeConfig[event.type]

  return (
    <div className="flex gap-4">
      {/* Timeline line + icon */}
      <div className="flex flex-col items-center flex-shrink-0">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
          style={{ background: config.iconBg, color: config.iconColor }}
        >
          <TypeIcon type={event.type} />
        </div>
        {!isLast && (
          <div
            className="w-px flex-1 mt-1"
            style={{ background: '#E8E5DF', minHeight: 24 }}
          />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="text-xs font-semibold px-2 py-0.5 rounded-full"
                style={{ background: config.chipBg, color: config.chipText }}
              >
                {config.label}
              </span>
              <code
                className="text-xs font-semibold"
                style={{ color: '#374151', fontFamily: 'var(--font-geist-mono, monospace)' }}
              >
                {event.service}
              </code>
              {event.prNumber && (
                <span className="text-xs" style={{ color: '#9CA3AF' }}>
                  PR #{event.prNumber}
                </span>
              )}
              {event.field && (
                <code className="text-xs" style={{ color: '#9CA3AF', fontFamily: 'var(--font-geist-mono, monospace)' }}>
                  {event.field}
                </code>
              )}
            </div>
            <p className="text-sm mt-1.5" style={{ color: '#374151' }}>
              {event.title}
            </p>
          </div>
          <span className="text-xs flex-shrink-0 mt-0.5" style={{ color: '#9CA3AF' }}>
            {event.timeAgo}
          </span>
        </div>
      </div>
    </div>
  )
}
