'use client'

import { useState, useEffect } from 'react'
import TopBar from '@/components/dashboard/TopBar'
import { api, ApiField, ApiDisagreement } from '@/lib/api'

type FieldStatus = 'stable' | 'breaking' | 'changed'

const statusStyle: Record<FieldStatus, { bg: string; text: string; label: string }> = {
  stable:   { bg: '#ECFDF5', text: '#065F46', label: 'Stable' },
  changed:  { bg: '#FFFBEB', text: '#92400E', label: 'Changed' },
  breaking: { bg: '#FEF2F2', text: '#9B1C1C', label: 'Breaking' },
}

const filters: { label: string; value: FieldStatus | 'all' }[] = [
  { label: 'All',      value: 'all' },
  { label: 'Breaking', value: 'breaking' },
  { label: 'Changed',  value: 'changed' },
  { label: 'Stable',   value: 'stable' },
]

function fieldStatus(fqn: string, disagreements: ApiDisagreement[]): FieldStatus {
  const d = disagreements.find((d) => d.field_fqn === fqn && !d.resolved_at)
  if (!d) return 'stable'
  return d.severity === 'CRITICAL' || d.severity === 'HIGH' ? 'breaking' : 'changed'
}

export default function FieldsPage() {
  const [fields, setFields] = useState<ApiField[]>([])
  const [disagreements, setDisagreements] = useState<ApiDisagreement[]>([])
  const [loading, setLoading] = useState(true)
  const [activeFilter, setActiveFilter] = useState<FieldStatus | 'all'>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    Promise.all([api.fields(), api.disagreements()])
      .then(([f, d]) => { setFields(f); setDisagreements(d) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const enriched = fields.map((f) => ({
    ...f,
    status: fieldStatus(f.fqn, disagreements),
  }))

  const filtered = enriched.filter((f) => {
    const matchFilter = activeFilter === 'all' || f.status === activeFilter
    const matchSearch =
      search === '' ||
      f.name.toLowerCase().includes(search.toLowerCase()) ||
      f.producer_service.toLowerCase().includes(search.toLowerCase()) ||
      f.endpoint_or_topic.toLowerCase().includes(search.toLowerCase())
    return matchFilter && matchSearch
  })

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar title="Fields" subtitle="Every indexed field contract across all services" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-sm">
            <svg className="absolute left-3 top-1/2 -translate-y-1/2" width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ color: '#9CA3AF' }}>
              <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.3" />
              <path d="M9.5 9.5l3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            <input
              type="text"
              placeholder="Search fields, services, endpoints..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-8 pr-3 py-2 text-sm rounded-xl outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E8E5DF', color: '#111827' }}
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
                  color:      activeFilter === f.value ? '#FFFFFF'  : '#374151',
                  border:     activeFilter === f.value ? 'none'      : '1px solid #E8E5DF',
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="text-sm text-gray-400 py-12 text-center">Loading fields…</div>
        ) : (
          <>
            <div className="rounded-2xl overflow-hidden" style={{ border: '1px solid #E8E5DF' }}>
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ background: '#F8F7F4', borderBottom: '1px solid #E8E5DF' }}>
                    {['Field Name', 'Type', 'Service', 'Endpoint', 'Nullable', 'Status'].map((col) => (
                      <th key={col} className="text-left px-5 py-3 text-xs font-semibold uppercase tracking-wider" style={{ color: '#6B7280' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((field, i) => {
                    const ss = statusStyle[field.status]
                    return (
                      <tr key={field.fqn} style={{ background: i % 2 === 0 ? '#FFFFFF' : '#FDFCFA', borderBottom: i < filtered.length - 1 ? '1px solid #F3F4F6' : 'none' }}>
                        <td className="px-5 py-3.5">
                          <code className="text-sm font-semibold" style={{ color: '#111827', fontFamily: 'monospace' }}>
                            {field.name}
                          </code>
                        </td>
                        <td className="px-5 py-3.5">
                          <code className="text-xs px-2 py-0.5 rounded" style={{ background: '#F3F4F6', color: '#374151', fontFamily: 'monospace' }}>
                            {field.declared_type}
                          </code>
                        </td>
                        <td className="px-5 py-3.5">
                          <code className="text-xs font-medium" style={{ color: '#374151', fontFamily: 'monospace' }}>
                            {field.producer_service}
                          </code>
                        </td>
                        <td className="px-5 py-3.5">
                          <code className="text-xs" style={{ color: '#9CA3AF', fontFamily: 'monospace' }}>
                            {field.endpoint_or_topic}
                          </code>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="text-xs" style={{ color: field.nullable ? '#6B7280' : '#9B1C1C' }}>
                            {field.nullable ? 'nullable' : 'required'}
                          </span>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="text-xs font-semibold px-2.5 py-1 rounded-full" style={{ background: ss.bg, color: ss.text }}>
                            {ss.label}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-5 py-8 text-center text-sm" style={{ color: '#9CA3AF' }}>
                        No fields match your filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="text-xs mt-3" style={{ color: '#9CA3AF' }}>
              Showing {filtered.length} of {fields.length} fields across all services
            </p>
          </>
        )}
      </div>
    </div>
  )
}
