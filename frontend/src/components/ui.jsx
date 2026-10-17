// Shared UI building blocks.
import { useEffect, useId, useState } from 'react'

export function Button({ variant = 'primary', size, className = '', ...props }) {
  const classes = ['btn', `btn-${variant}`, size === 'sm' ? 'btn-sm' : '', className].filter(Boolean).join(' ')
  return <button className={classes} {...props} />
}

export function Field({ label, error, hint, children }) {
  const id = useId()
  const child = typeof children === 'function' ? children(id) : children
  return (
    <div className={`field ${error ? 'field-error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {child}
      {error ? <p className="field-message">{error}</p> : hint ? <p className="field-hint">{hint}</p> : null}
    </div>
  )
}

export function Alert({ tone = 'error', title, children }) {
  if (!title && !children) return null
  return (
    <div className={`alert alert-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {title && <strong>{title}</strong>}
      {children && <span>{children}</span>}
    </div>
  )
}

export function Badge({ tone = 'neutral', children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function Card({ title, actions, children }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  )
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

// Turns an ApiError into {field: message} for forms.
export function fieldErrorsOf(error) {
  const out = {}
  for (const e of error?.fieldErrors || []) {
    if (e.field) out[e.field] = e.message
  }
  return out
}

const dateFormat = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatDateTime(value) {
  return value ? dateFormat.format(new Date(value)) : '—'
}

const dayFormat = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }) // YYYY-MM-DD

export function formatDate(value) {
  return value ? dayFormat.format(new Date(value)) : '—'
}

export function Drawer({ title, subtitle, onClose, children, footer }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header className="drawer-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer && <footer className="drawer-footer">{footer}</footer>}
      </aside>
    </div>
  )
}

// Page numbers with gaps: 1 … 4 5 [6] 7 8 … 20
function pageList(current, last) {
  const pages = new Set([1, last, current - 1, current, current + 1])
  if (current <= 3) [2, 3, 4].forEach((p) => pages.add(p))
  if (current >= last - 2) [last - 1, last - 2, last - 3].forEach((p) => pages.add(p))
  const sorted = [...pages].filter((p) => p >= 1 && p <= last).sort((a, b) => a - b)
  const out = []
  sorted.forEach((p, i) => {
    if (i && p - sorted[i - 1] > 1) out.push('gap-' + p)
    out.push(p)
  })
  return out
}

export function Pagination({ total, limit, offset, onChange, onLimitChange }) {
  const page = Math.floor(offset / limit) + 1
  const last = Math.max(1, Math.ceil(total / limit))
  const from = total ? offset + 1 : 0
  const to = Math.min(offset + limit, total)
  return (
    <div className="pagination">
      <span className="muted small">
        Showing <strong>{from}–{to}</strong> of <strong>{total}</strong>
      </span>
      <div className="pagination-controls">
        <select value={limit} onChange={(e) => onLimitChange(Number(e.target.value))} aria-label="Rows per page">
          {[25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </select>
        <button className="page-btn" disabled={page === 1} onClick={() => onChange((page - 2) * limit)}>
          Previous
        </button>
        {pageList(page, last).map((p) =>
          typeof p === 'string' ? (
            <span key={p} className="page-gap">
              …
            </span>
          ) : (
            <button
              key={p}
              className={`page-btn ${p === page ? 'active' : ''}`}
              aria-current={p === page ? 'page' : undefined}
              onClick={() => onChange((p - 1) * limit)}
            >
              {p}
            </button>
          ),
        )}
        <button className="page-btn" disabled={page === last} onClick={() => onChange(page * limit)}>
          Next
        </button>
      </div>
    </div>
  )
}

export function ErrorAlert({ error }) {
  if (!error) return null
  return <Alert title={error.title}>{error.message !== error.title ? error.message : null}</Alert>
}

export function ConfirmModal({ title, children, confirmLabel, danger, busy, onConfirm, onClose }) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="stack">
        {children}
        <div className="row-end">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant={danger ? 'danger-solid' : 'primary'} onClick={onConfirm} disabled={busy}>
            {busy ? 'Working…' : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// Idempotency keys must work on plain http too, where crypto.randomUUID is unavailable.
export function newRequestKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

const LIFECYCLE = {
  draft: { tone: 'amber', label: 'Yet to be approved' },
  pending: { tone: 'blue', label: 'Waiting for admin approval' },
  approved: { tone: 'green', label: 'Approved' },
}

export function LifecycleBadge({ lifecycle }) {
  const { tone, label } = LIFECYCLE[lifecycle] || LIFECYCLE.draft
  return <Badge tone={tone}>{label}</Badge>
}

export function useDebounced(value, ms) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
