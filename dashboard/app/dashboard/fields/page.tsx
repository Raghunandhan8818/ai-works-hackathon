'use client'

import { useState } from 'react'
import TopBar from '@/components/dashboard/TopBar'
import { fields } from '@/lib/mock-data'
import { FieldStatus } from '@/lib/types'

const statusStyle: Record<FieldStatus, { bg: string; text: string; label: string }> = {
  stable: { bg: '#ECFDF5', text: '#065F46', label: 'Stable' },
  changed: { bg: '#FFFBEB', text: '#92400E', label: 'Changed' },
  breaking: { bg: '#FEF2F2', text: '#9B1C1C', label: 'Breaking' },
}

const filters: { label: string; value: FieldStatus | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Breaking', value: 'breaking' },
  { label: 'Changed', value: 'changed' },
  { label: 'Stable', value: 'stable' },
]

export default function FieldsPage() {
  const [activeFilter, setActiveFilter] = useState<FieldStatus | 'all'>('all')
  const [search, setSearch] = useState('')

  const filtered = fields.filter((f) => {
    const matchesFilter = activeFilter === 'all' || f.status === activeFilter
    const matchesSearch =
      search === '' ||
      f.name.toLowerCase().includes(search.toLowerCase()) ||
      f.service.toLowerCase().includes(search.toLowerCase())
    return matchesFilter && matchesSearch
  })

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar
        title="Fields"
        subtitle="Every indexed field contract across all services"
      />

      <div className="flex-1 overflow-y-auto p-6">
        {/* Search + filter */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-sm">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2"
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              style={{ color: '#9CA3AF' }}
            >
              <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.3" />
              <path d="M9.5 9.5l3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Search fields or services..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-2 text-sm rounded-xl outline-none"
              style={{
                background: '#FFFFFF',
                border: '1px solid #E8E5DF',
                color: '#111827',
              }}
            />
          </div>

          <div className="flex items-center gap-1.5">
            {filters.map((f) => (
              <button
                key={f.value}
                onClick={() => setActiveFilter(f.value)}
                className="text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                style={{
                  background: activeFilter === f.value ? '#111827' : '#F3F4F6',
                  color: activeFilter === f.value ? '#FFFFFF' : '#374151',
                  border: activeFilter === f.value ? 'none' : '1px solid #E8E5DF',
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="rounded-2xl overflow-hidden" style={{ border: '1px solid #E8E5DF' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: '#F8F7F4', borderBottom: '1px solid #E8E5DF' }}>
                {['Field Name', 'Type', 'Service', 'Consumers', 'Status', 'Last Changed'].map(
                  (col) => (
                    <th
                      key={col}
                      className="text-left px-5 py-3 text-xs font-semibold uppercase tracking-wider"
                      style={{ color: '#6B7280' }}
                    >
                      {col}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((field, i) => {
                const ss = statusStyle[field.status]
                return (
                  <tr
                    key={field.id}
                    style={{
                      background: i % 2 === 0 ? '#FFFFFF' : '#FDFCFA',
                      borderBottom: i < filtered.length - 1 ? '1px solid #F3F4F6' : 'none',
                    }}
                  >
                    <td className="px-5 py-3.5">
                      <code
                        className="text-sm font-semibold"
                        style={{ color: '#111827', fontFamily: 'var(--font-geist-mono, monospace)' }}
                      >
                        {field.name}
                      </code>
                    </td>
                    <td className="px-5 py-3.5">
                      <code
                        className="text-xs px-2 py-0.5 rounded"
                        style={{ background: '#F3F4F6', color: '#374151', fontFamily: 'var(--font-geist-mono, monospace)' }}
                      >
                        {field.type}
                      </code>
                    </td>
                    <td className="px-5 py-3.5">
                      <code
                        className="text-xs font-medium"
                        style={{ color: '#374151', fontFamily: 'var(--font-geist-mono, monospace)' }}
                      >
                        {field.service}
                      </code>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1.5">
                        <div className="flex -space-x-1">
                          {Array.from({ length: Math.min(field.consumers, 4) }).map((_, idx) => (
                            <div
                              key={idx}
                              className="w-5 h-5 rounded-full border-2 border-white flex items-center justify-center text-xs font-bold"
                              style={{ background: '#E8E5DF', color: '#6B7280' }}
                            />
                          ))}
                        </div>
                        <span className="text-xs" style={{ color: '#6B7280' }}>
                          {field.consumers}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span
                        className="text-xs font-semibold px-2.5 py-1 rounded-full"
                        style={{ background: ss.bg, color: ss.text }}
                      >
                        {ss.label}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-xs" style={{ color: '#9CA3AF' }}>
                      {field.lastChanged}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <p className="text-xs mt-3" style={{ color: '#9CA3AF' }}>
          Showing {filtered.length} of {fields.length} fields · 47 total across all services
        </p>
      </div>
    </div>
  )
}
