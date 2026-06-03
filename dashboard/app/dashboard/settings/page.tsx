'use client'

import { useState, useEffect } from 'react'
import TopBar from '@/components/dashboard/TopBar'
import { api } from '@/lib/api'

const modelProviders = [
  { id: 'anthropic', label: 'Anthropic Claude', models: ['claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'] },
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini', 'o1'] },
  { id: 'gemini', label: 'Google Gemini', models: ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'] },
  { id: 'ollama', label: 'Ollama (Local)', models: ['llama3.1:8b', 'codellama:13b', 'mistral:7b'] },
]

function extractGitHubOwner(repoUrl: string): string | null {
  const m = repoUrl.match(/github\.com\/([^/]+)/)
  return m ? m[1] : null
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: 'var(--dash-card)', border: '1px solid var(--dash-border)' }}>
      <div className="px-6 py-4" style={{ borderBottom: '1px solid var(--dash-border)' }}>
        <h2 className="text-base font-semibold" style={{ fontFamily: 'var(--font-syne)', color: 'var(--dash-text)' }}>
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
        <p className="text-sm font-medium" style={{ color: 'var(--dash-text)' }}>
          {label}
        </p>
        {hint && (
          <p className="text-xs mt-0.5" style={{ color: 'var(--dash-text-secondary)' }}>
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
  const [githubOrg, setGithubOrg] = useState<string | null>(null)
  const [serviceCount, setServiceCount] = useState<number>(0)
  const [connected, setConnected] = useState(false)
  const [archReviewEnabled, setArchReviewEnabled] = useState(false)

  useEffect(() => {
    api.services()
      .then((svcs: ApiService[]) => {
        const owner = svcs.map((s) => extractGitHubOwner(s.repo_url)).find(Boolean) ?? null
        setGithubOrg(owner)
        setServiceCount(svcs.length)
        setConnected(svcs.length > 0)
      })
      .catch(() => setConnected(false))

    api.getReviewEnabled()
      .then((r) => setArchReviewEnabled(r.architectural_review_enabled))
      .catch(() => {})
  }, [])

  const handleArchReviewToggle = async () => {
    const next = !archReviewEnabled
    setArchReviewEnabled(next)
    try {
      await api.setReviewEnabled(next)
    } catch (err) {
      console.error('[Ripple] Failed to persist architectural review toggle:', err)
      setArchReviewEnabled(!next)
    }
  }

  const currentProvider = modelProviders.find((p) => p.id === provider)!
  const orgInitials = githubOrg ? githubOrg.slice(0, 2).toUpperCase() : '??'

  const selectStyle = {
    background: 'var(--dash-bg)',
    border: '1px solid var(--dash-border)',
    color: 'var(--dash-text)',
  }

  const inputStyle = {
    background: 'var(--dash-bg)',
    border: '1px solid var(--dash-border)',
    color: 'var(--dash-text)',
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <TopBar title="Settings" subtitle="Model configuration, GitHub App, and Ripple preferences" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl space-y-6">

          {/* GitHub App */}
          <Section title="GitHub App">
            <FieldRow
              label="Connection status"
              hint={connected && githubOrg ? `GitHub App monitoring ${githubOrg} repos` : 'No services indexed yet'}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: connected ? '#22C55E' : '#9CA3AF' }}
                />
                <span className="text-sm font-medium" style={{ color: connected ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}>
                  {connected ? 'Connected' : 'Not configured'}
                </span>
              </div>
            </FieldRow>

            <FieldRow label="Organization" hint="All repos in this org are monitored">
              <div className="flex items-center gap-2">
                {githubOrg ? (
                  <>
                    <div
                      className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                      style={{ background: '#FF5A1F', color: '#FFFFFF' }}
                    >
                      {orgInitials}
                    </div>
                    <span className="text-sm font-mono" style={{ color: 'var(--dash-text)' }}>
                      {githubOrg}
                    </span>
                  </>
                ) : (
                  <span className="text-sm" style={{ color: 'var(--dash-text-secondary)' }}>
                    —
                  </span>
                )}
              </div>
            </FieldRow>

            <FieldRow label="Services indexed" hint="Services tracked in the knowledge graph">
              <span className="text-sm font-medium" style={{ color: 'var(--dash-text)' }}>
                {serviceCount > 0 ? `${serviceCount} service${serviceCount !== 1 ? 's' : ''}` : '—'}
              </span>
            </FieldRow>

            <FieldRow label="Webhook" hint="GitHub sends PR events to Ripple">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: connected ? '#22C55E' : '#9CA3AF' }}
                />
                <span className="text-sm" style={{ color: connected ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}>
                  {connected ? 'Active' : 'Inactive'}
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
                style={selectStyle}
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
                style={selectStyle}
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
                  style={inputStyle}
                />
              </FieldRow>
            )}

            {provider !== 'ollama' && (
              <FieldRow label="API Key" hint="Stored encrypted — never logged or shared">
                <input
                  type="password"
                  placeholder="sk-ant-••••••••••••••••"
                  className="w-full text-sm px-3 py-2 rounded-xl outline-none"
                  style={inputStyle}
                />
              </FieldRow>
            )}

            <div
              className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs"
              style={{ background: 'var(--dash-bg)', border: '1px solid var(--dash-border)', color: 'var(--dash-text-secondary)' }}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ flexShrink: 0 }}>
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
                <div className="flex justify-between text-xs" style={{ color: 'var(--dash-text-secondary)' }}>
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
                style={{ color: notifySlack ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: notifySlack ? '#22C55E' : 'var(--dash-border)' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                    style={{ background: 'var(--dash-sidebar)', left: notifySlack ? '1.25rem' : '0.125rem' }}
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
                style={{ color: notifyPR ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: notifyPR ? '#22C55E' : 'var(--dash-border)' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                    style={{ background: 'var(--dash-sidebar)', left: notifyPR ? '1.25rem' : '0.125rem' }}
                  />
                </div>
                {notifyPR ? 'On' : 'Off'}
              </button>
            </FieldRow>
          </Section>

          <Section title="Architectural Review">
            <FieldRow
              label="Enable Architectural Review"
              hint="When on, Ripple posts a single consolidated review covering contract drift, architectural violations, security concerns, and performance suggestions. Add an ARCHITECTURE.md to your repos to encode constraints."
            >
              <button
                onClick={handleArchReviewToggle}
                className="flex items-center gap-2 text-sm font-medium transition-colors"
                style={{ color: archReviewEnabled ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: archReviewEnabled ? '#22C55E' : 'var(--dash-border)' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                    style={{ background: 'var(--dash-sidebar)', left: archReviewEnabled ? '1.25rem' : '0.125rem' }}
                  />
                </div>
                {archReviewEnabled ? 'On' : 'Off'}
              </button>
            </FieldRow>

            <FieldRow
              label="How it works"
              hint=""
            >
              <div
                className="text-xs leading-relaxed"
                style={{ color: 'var(--dash-text-secondary)' }}
              >
                Add <code className="font-mono px-1 rounded" style={{ background: 'var(--dash-bg)' }}>ARCHITECTURE.md</code> to any repo.
                On PRs, Ripple reads it + any learned rules and posts one structured review.
                Reply <code className="font-mono px-1 rounded" style={{ background: 'var(--dash-bg)' }}>/learn &lt;correction&gt;</code> on a review comment to teach Ripple your architectural patterns.
              </div>
            </FieldRow>
          </Section>

          {/* Save */}
          <div className="flex justify-end">
            <button
              className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all"
              style={{ background: 'var(--dash-text)', color: 'var(--dash-sidebar)' }}
            >
              Save settings
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
