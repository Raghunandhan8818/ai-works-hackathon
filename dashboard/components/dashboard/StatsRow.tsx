'use client'

import { useEffect, useState } from 'react'
import { api, ApiService, ApiField, ApiDisagreement } from '@/lib/api'

export default function StatsRow() {
  const [services, setServices] = useState<ApiService[]>([])
  const [fields, setFields] = useState<ApiField[]>([])
  const [disagreements, setDisagreements] = useState<ApiDisagreement[]>([])

  useEffect(() => {
    Promise.all([api.services(), api.fields(), api.disagreements()])
      .then(([s, f, d]) => {
        setServices(s)
        setFields(f)
        setDisagreements(d)
      })
      .catch(() => {/* backend not reachable — keep zeros */})
  }, [])

  const stats = [
    {
      value: services.length,
      label: 'SERVICES',
      color: '#111827',
      bg: '#F8F7F4',
      border: '#E8E5DF',
    },
    {
      value: disagreements.length,
      label: 'DISAGREEMENTS',
      color: disagreements.length > 0 ? '#92400E' : '#065F46',
      bg: disagreements.length > 0 ? '#FFFBEB' : '#ECFDF5',
      border: disagreements.length > 0 ? '#FDE68A' : '#6EE7B7',
    },
    {
      value: services.filter((s) => s.role === 'consumer' || s.role === 'both').length,
      label: 'CONSUMERS',
      color: '#065F46',
      bg: '#ECFDF5',
      border: '#6EE7B7',
    },
    {
      value: fields.length,
      label: 'FIELDS INDEXED',
      color: '#111827',
      bg: '#F8F7F4',
      border: '#E8E5DF',
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded-2xl px-6 py-5"
          style={{ background: stat.bg, border: `1px solid ${stat.border}` }}
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
