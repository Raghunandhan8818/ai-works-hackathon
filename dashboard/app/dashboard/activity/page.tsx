import TopBar from '@/components/dashboard/TopBar'
import ActivityItem from '@/components/activity/ActivityItem'
import { activityEvents } from '@/lib/mock-data'

export default function ActivityPage() {
  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Activity"
        subtitle="Full audit trail — every PR analysis, auto-heal, fix PR, and interrupt"
      />

      <div className="flex-1 overflow-y-auto p-6">
        {/* Filter bar */}
        <div className="flex items-center gap-2 mb-6">
          {['All', 'PR Analyzed', 'Auto-Healed', 'Fix PRs', 'Interrupts', 'Indexed'].map(
            (filter, i) => (
              <button
                key={filter}
                className="text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                style={{
                  background: i === 0 ? '#111827' : '#F3F4F6',
                  color: i === 0 ? '#FFFFFF' : '#374151',
                  border: i === 0 ? 'none' : '1px solid #E8E5DF',
                }}
              >
                {filter}
              </button>
            )
          )}
        </div>

        {/* Timeline */}
        <div className="max-w-2xl">
          {activityEvents.map((event, index) => (
            <ActivityItem
              key={event.id}
              event={event}
              isLast={index === activityEvents.length - 1}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
