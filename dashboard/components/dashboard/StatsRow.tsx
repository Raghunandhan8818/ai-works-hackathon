'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, ApiDisagreement, ApiField } from '@/lib/api'

export default function StatsRow() {
  const [disagreements, setDisagreements] = useState<ApiDisagreement[]>([])
  const [fields, setFields] = useState<ApiField[]>([])

  useEffect(() => {
    Promise.all([api.allDisagreements(), api.fields()])
      .then(([d, f]) => {
        setDisagreements(d)
        setFields(f)
      })
      .catch(() => {/* backend not reachable — keep zeros */})
  }, [])

  const activeInterrupts = disagreements.filter(
    (d) => d.requires_human_decision && d.resolved_at === null
  ).length

  const autoFixed = disagreements.filter(
    (d) => !d.requires_human_decision && d.fix_pr_url && d.fix_pr_url !== '' && d.resolved_at === null
  ).length

  const fixPending = disagreements.filter(
    (d) => !d.requires_human_decision && (!d.fix_pr_url || d.fix_pr_url === '') && d.resolved_at === null
  ).length

  const resolved = disagreements.filter((d) => d.resolved_at !== null).length

  const stats = [
    {
      value: activeInterrupts,
      label: 'ACTIVE INTERRUPTS',
      color: activeInterrupts > 0 ? '#92400E' : '#065F46',
      bg: activeInterrupts > 0 ? '#FFFBEB' : '#ECFDF5',
      border: activeInterrupts > 0 ? '#FDE68A' : '#6EE7B7',
      href: '/dashboard/interrupts',
    },
    {
      value: autoFixed + fixPending,
      label: fixPending > 0 ? 'AUTO-FIXING' : 'AUTO-FIXED',
      color: fixPending > 0 ? '#1D4ED8' : '#065F46',
      bg: fixPending > 0 ? '#EFF6FF' : '#ECFDF5',
      border: fixPending > 0 ? '#BFDBFE' : '#6EE7B7',
      href: '/dashboard/activity',
    },
    {
      value: resolved,
      label: 'RESOLVED',
      color: '#374151',
      bg: '#F3F4F6',
      border: '#D1D5DB',
      href: '/dashboard/activity',
    },
    {
      value: fields.length,
      label: 'FIELDS INDEXED',
      color: '#111827',
      bg: '#F8F7F4',
      border: '#E8E5DF',
      href: undefined,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat) => {
        const inner = (
          <div
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
        )

        return stat.href ? (
          <Link key={stat.label} href={stat.href} className="block hover:opacity-90 transition-opacity">
            {inner}
          </Link>
        ) : (
          <div key={stat.label}>{inner}</div>
        )
      })}
    </div>
  )
}
