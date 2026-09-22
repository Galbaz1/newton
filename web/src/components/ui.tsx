/** Small presentational primitives shared by all features. No data fetching. */
import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, XCircle } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useLocale } from '../lib/locale'

export type Tone = 'ready' | 'missing' | 'error' | 'superseded' | 'neutral'

const toneIcons = {
  ready: CheckCircle2,
  missing: CircleDashed,
  error: XCircle,
  superseded: Info,
  neutral: Info,
}

/** Status pill. Text always states the status; colour is only reinforcement. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = toneIcons[tone]
  return (
    <span className={`badge badge-${tone}`}>
      <Icon size={13} aria-hidden="true" />
      {children}
    </span>
  )
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  busy?: boolean
}

export function Button({ variant = 'secondary', busy = false, children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`btn btn-${variant} ${rest.className ?? ''}`}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
    >
      {busy && <Loader2 size={14} className="spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="spinner" role="status">
      <Loader2 size={15} className="spin" aria-hidden="true" />
      {label}
    </p>
  )
}

/** Inline message for API errors, warnings and honest "not available" notes. */
export function Notice({
  tone,
  children,
  onRetry,
}: {
  tone: 'error' | 'warning' | 'info'
  children: ReactNode
  onRetry?: () => void
}) {
  const { text } = useLocale()
  const Icon = tone === 'info' ? Info : AlertTriangle
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon size={15} aria-hidden="true" />
      <div className="notice-body">{children}</div>
      {onRetry && (
        <button type="button" className="link" onClick={onRetry}>
          {text({ en: 'Retry', nl: 'Opnieuw proberen' })}
        </button>
      )}
    </div>
  )
}

/** Explains what is missing and what adding it enables; never shows demo data. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function SectionHeader({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {aside}
    </div>
  )
}
