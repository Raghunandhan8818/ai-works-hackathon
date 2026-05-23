'use client'

import { NodeProps, Handle, Position } from 'reactflow'
import { ServiceStatus } from '@/lib/types'

interface ServiceNodeData {
  label: string
  status: ServiceStatus
  hasInterrupt?: boolean
  onNodeClick?: (id: string) => void
}

const statusStyles: Record<ServiceStatus, { bg: string; text: string; border: string; pulseClass: string }> = {
  healthy: {
    bg: '#FFFFFF',
    text: '#065F46',
    border: '#22C55E',
    pulseClass: '',
  },
  healed: {
    bg: '#ECFDF5',
    text: '#065F46',
    border: '#22C55E',
    pulseClass: 'node-pulse-green',
  },
  interrupt: {
    bg: '#FFFBEB',
    text: '#92400E',
    border: '#F59E0B',
    pulseClass: 'node-pulse-amber',
  },
  breaking: {
    bg: '#FEF2F2',
    text: '#9B1C1C',
    border: '#EF4444',
    pulseClass: 'node-pulse-red',
  },
}

const statusLabel: Record<ServiceStatus, string> = {
  healthy: 'healthy',
  healed: 'healed',
  interrupt: 'interrupt',
  breaking: 'breaking',
}

export default function ServiceNode({ id, data }: NodeProps<ServiceNodeData>) {
  const { label, status, hasInterrupt } = data
  const styles = statusStyles[status]

  return (
    <div
      className={`relative ${styles.pulseClass}`}
      style={{
        background: styles.bg,
        border: `2px solid ${styles.border}`,
        borderRadius: 12,
        padding: '10px 16px',
        minWidth: 160,
        boxShadow: `0 0 0 1px ${styles.border}22`,
        cursor: 'pointer',
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: styles.border, width: 8, height: 8, border: 'none' }}
      />

      <div className="flex items-center gap-2.5">
        {/* Server icon */}
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: `${styles.border}20` }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
            <rect x="1" y="2" width="12" height="4" rx="1" stroke={styles.border} strokeWidth="1.2" />
            <rect x="1" y="8" width="12" height="4" rx="1" stroke={styles.border} strokeWidth="1.2" />
            <circle cx="3.5" cy="4" r="0.8" fill={styles.border} />
            <circle cx="3.5" cy="10" r="0.8" fill={styles.border} />
          </svg>
        </div>

        <div className="min-w-0">
          <div
            className="text-xs font-bold leading-tight truncate"
            style={{ fontFamily: 'var(--font-geist-mono, monospace)', color: styles.text, maxWidth: 110 }}
          >
            {label}
          </div>
          <div
            className="text-xs mt-0.5 font-medium"
            style={{ color: `${styles.border}cc` }}
          >
            {statusLabel[status]}
          </div>
        </div>
      </div>

      {/* Interrupt badge */}
      {hasInterrupt && (
        <div
          className="absolute -top-2 -right-2 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
          style={{ background: '#F59E0B', color: '#FFFFFF', border: '2px solid #FFFFFF' }}
        >
          !
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        style={{ background: styles.border, width: 8, height: 8, border: 'none' }}
      />
    </div>
  )
}
