'use client'

import { useState } from 'react'
import TopBar from '@/components/dashboard/TopBar'

const modelProviders = [
  { id: 'anthropic', label: 'Anthropic Claude', models: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'] },
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'o1'] },
  { id: 'gemini', label: 'Google Gemini', models: ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'] },
  { id: 'ollama', label: 'Ollama (Local)', models: ['llama3.1:8b', 'codellama:13b', 'mistral:7b'] },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: '#FFFFFF', border: '1px solid #E8E5DF' }}>
      <div className="px-6 py-4" style={{ borderBottom: '1px solid #F3F4F6' }}>
        <h2 className="text-base font-semibold" style={{ fontFamily: 'var(--font-syne)', color: '#111827' }}>
          {title}
        </h2>
      </div>
      <div className="px-6 py-5 space-y-5">{children}</div>
    </div>
  )
}

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-8">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium" style={{ color: '#111827' }}>
          {label}
        </p>
        {hint && (
          <p className="text-xs mt-0.5" style={{ color: '#9CA3AF' }}>
            {hint}
          </p>
        )}
      </div>
      <div className="flex-shrink-0 w-72">{children}</div>
    </div>
  )
}

export default function SettingsPage() {
  const [provider, setProvider] = useState('anthropic')
  const [model, setModel] = useState('claude-sonnet-4-6')
  const [autoFixThreshold, setAutoFixThreshold] = useState(80)
  const [notifySlack, setNotifySlack] = useState(true)
  const [notifyPR, setNotifyPR] = useState(true)

  const currentProvider = modelProviders.find((p) => p.id === provider)!

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar title="Settings" subtitle="Model configuration, GitHub App, and Ripple preferences" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl space-y-6">

          {/* GitHub App */}
          <Section title="GitHub App">
            <FieldRow label="Connection status" hint="GitHub App installed on spring-petclinic org">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: '#22C55E' }}
                />
                <span className="text-sm font-medium" style={{ color: '#065F46' }}>
                  Connected
                </span>
              </div>
            </FieldRow>

            <FieldRow label="Organization" hint="All repos in this org are monitored">
              <div className="flex items-center gap-2">
                <div
                  className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                  style={{ background: '#FF5A1F', color: '#FFFFFF' }}
                >
                  SP
                </div>
                <span className="text-sm" style={{ color: '#111827' }}>
                  spring-petclinic
                </span>
              </div>
            </FieldRow>

            <FieldRow label="Webhook" hint="GitHub sends PR events to Ripple">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: '#22C55E' }}
                />
                <span className="text-sm" style={{ color: '#065F46' }}>
                  Active · Last received 2h ago
                </span>
              </div>
            </FieldRow>
          </Section>

          {/* Model Config */}
          <Section title="Model Configuration">
            <FieldRow
              label="LLM Provider"
              hint="Ripple uses LiteLLM — any provider works with the same interface"
            >
              <select
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value)
                  const p = modelProviders.find((x) => x.id === e.target.value)!
                  setModel(p.models[0])
                }}
                className="w-full text-sm px-3 py-2 rounded-xl outline-none"
                style={{ background: '#F8F7F4', border: '1px solid #E8E5DF', color: '#111827' }}
              >
                {modelProviders.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </FieldRow>

            <FieldRow
              label="Model"
              hint="Used for semantic analysis and fix generation"
            >
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-xl outline-none"
                style={{ background: '#F8F7F4', border: '1px solid #E8E5DF', color: '#111827' }}
              >
                {currentProvider.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </FieldRow>

            {provider === 'ollama' && (
              <FieldRow
                label="Ollama endpoint"
                hint="Your local Ollama instance — code never leaves your network"
              >
                <input
                  type="text"
                  defaultValue="http://localhost:11434"
                  className="w-full text-sm px-3 py-2 rounded-xl outline-none font-mono"
                  style={{ background: '#F8F7F4', border: '1px solid #E8E5DF', color: '#111827' }}
                />
              </FieldRow>
            )}

            {provider !== 'ollama' && (
              <FieldRow label="API Key" hint="Stored encrypted — never logged or shared">
                <input
                  type="password"
                  placeholder="sk-ant-••••••••••••••••"
                  className="w-full text-sm px-3 py-2 rounded-xl outline-none"
                  style={{ background: '#F8F7F4', border: '1px solid #E8E5DF', color: '#111827' }}
                />
              </FieldRow>
            )}

            <div
              className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs"
              style={{ background: '#F8F7F4', border: '1px solid #E8E5DF', color: '#6B7280' }}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0, color: '#9CA3AF' }}>
                <path d="M7 1a6 6 0 100 12A6 6 0 007 1z" stroke="currentColor" strokeWidth="1.3" />
                <path d="M7 6.5v4M7 4.5v.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
              Ripple uses Haiku for structural profiling (cheap) and Sonnet for semantic decisions (accurate). Opus for the most ambiguous cases.
            </div>
          </Section>

          {/* Ripple Config */}
          <Section title="Ripple Preferences">
            <FieldRow
              label="Auto-fix confidence threshold"
              hint={`${autoFixThreshold}% — Ripple auto-fixes when confidence is above this. Below → sends interrupt.`}
            >
              <div className="space-y-1">
                <input
                  type="range"
                  min={50}
                  max={99}
                  value={autoFixThreshold}
                  onChange={(e) => setAutoFixThreshold(Number(e.target.value))}
                  className="w-full accent-orange-500"
                />
                <div className="flex justify-between text-xs" style={{ color: '#9CA3AF' }}>
                  <span>50% (more interrupts)</span>
                  <span className="font-semibold" style={{ color: '#FF5A1F' }}>
                    {autoFixThreshold}%
                  </span>
                  <span>99% (fewer interrupts)</span>
                </div>
              </div>
            </FieldRow>

            <FieldRow
              label="Notify on Slack"
              hint="Post interrupt and fix PR notifications to #ripple channel"
            >
              <button
                onClick={() => setNotifySlack(!notifySlack)}
                className="flex items-center gap-2 text-sm font-medium transition-colors"
                style={{ color: notifySlack ? '#065F46' : '#6B7280' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: notifySlack ? '#22C55E' : '#D1D5DB' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
                    style={{ left: notifySlack ? '1.25rem' : '0.125rem' }}
                  />
                </div>
                {notifySlack ? 'On' : 'Off'}
              </button>
            </FieldRow>

            <FieldRow
              label="Post bot comment on producer PR"
              hint="Ripple posts a summary comment listing affected consumers"
            >
              <button
                onClick={() => setNotifyPR(!notifyPR)}
                className="flex items-center gap-2 text-sm font-medium transition-colors"
                style={{ color: notifyPR ? '#065F46' : '#6B7280' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: notifyPR ? '#22C55E' : '#D1D5DB' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
                    style={{ left: notifyPR ? '1.25rem' : '0.125rem' }}
                  />
                </div>
                {notifyPR ? 'On' : 'Off'}
              </button>
            </FieldRow>
          </Section>

          {/* Save */}
          <div className="flex justify-end">
            <button
              className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
              style={{ background: '#111827', color: '#FFFFFF' }}
            >
              Save settings
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
