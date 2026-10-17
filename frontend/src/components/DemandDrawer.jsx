import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import LetterPreview from './LetterPreview'
import { DownloadIcon } from './icons'
import { api } from '../api/client'
import { Alert, Badge, Button, Drawer, ErrorAlert, Field, fieldErrorsOf, formatDate, formatDateTime, LifecycleBadge } from './ui'

const FIELDS = [
  { key: 'country', label: 'Country' },
  { key: 'employer', label: 'Employer' },
  { key: 'vacancy', label: 'Vacancy (total)', type: 'number' },
  { key: 'target_timeline', label: 'Target timeline' },
  { key: 'assign_to', label: 'Assign to' },
]

function toForm(demand) {
  const form = {}
  for (const f of FIELDS) form[f.key] = demand[f.key] ?? ''
  return form
}

function toTrades(demand) {
  return demand.trades.map((t) => ({ project: t.project ?? '', trade: t.trade, quantity: String(t.quantity) }))
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)

// Details of one demand letter. In Milestone 3–4 the letter preview joins this panel.
// readOnly: only the letter preview, nothing can be changed (Create Advertisement page).
export default function DemandDrawer({ demandId, onClose, onSaved, readOnly = false }) {
  const [demand, setDemand] = useState(null)
  const [form, setForm] = useState(null)
  const [trades, setTrades] = useState([])
  const [error, setError] = useState(null)
  const [conflict, setConflict] = useState(false)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('letter')
  const [letter, setLetter] = useState(undefined) // undefined = loading, null = none yet

  useEffect(() => {
    api(`/demands/${demandId}/letter`)
      .then(setLetter)
      .catch((err) => (err.status === 404 ? setLetter(null) : setError(err)))
  }, [demandId])

  const load = useCallback(async () => {
    const data = await api(`/demands/${demandId}`)
    setDemand(data)
    setForm(toForm(data))
    setTrades(toTrades(data))
    setConflict(false)
    setError(null)
  }, [demandId])

  useEffect(() => {
    load().catch(setError)
  }, [load])

  if (!demand) {
    return (
      <Drawer title="Demand letter" onClose={onClose}>
        {error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>}
      </Drawer>
    )
  }

  const fieldsDirty = !same(form, toForm(demand))
  const tradesDirty = !same(trades, toTrades(demand))
  const dirty = fieldsDirty || tradesDirty
  const errors = fieldErrorsOf(error)

  function setField(key) {
    return (e) => {
      setSaved(false)
      setForm({ ...form, [key]: e.target.value })
    }
  }

  function setTrade(index, key, value) {
    setSaved(false)
    setTrades(trades.map((t, i) => (i === index ? { ...t, [key]: value } : t)))
  }

  async function save() {
    setBusy(true)
    setError(null)
    setSaved(false)
    let etag = demand.etag
    try {
      if (fieldsDirty) {
        const body = {}
        for (const f of FIELDS) {
          if (form[f.key] !== (demand[f.key] ?? '')) {
            body[f.key] = f.type === 'number' ? (form[f.key] === '' ? null : Number(form[f.key])) : form[f.key]
          }
        }
        const updated = await api(`/demands/${demandId}`, { method: 'PATCH', body, headers: { 'If-Match': etag } })
        etag = updated.etag
        setDemand(updated)
      }
      if (tradesDirty) {
        const body = trades
          .filter((t) => t.trade.trim() || t.quantity)
          .map((t) => ({ project: t.project, trade: t.trade, quantity: Number(t.quantity) }))
        const updated = await api(`/demands/${demandId}/trades`, { method: 'PUT', body, headers: { 'If-Match': etag } })
        setDemand(updated)
        setTrades(toTrades(updated))
      }
      await load()
      setSaved(true)
      onSaved?.()
    } catch (err) {
      if (err.status === 412) setConflict(true)
      else setError(err)
    } finally {
      setBusy(false)
    }
  }

  const tradeTotal = trades.reduce((sum, t) => sum + (Number(t.quantity) || 0), 0)

  return (
    <Drawer
      title={demand.demand_code}
      subtitle={
        demand.lifecycle === 'approved'
          ? `Approved ${formatDate(demand.approved_at)} by ${demand.approved_by?.display_name}`
          : demand.lifecycle === 'pending'
            ? `Waiting for admin approval · sent ${formatDateTime(demand.submitted_at)} by ${demand.submitted_by?.display_name}`
            : `Draft · started ${formatDateTime(demand.created_at)} by ${demand.created_by.display_name}`
      }
      onClose={onClose}
      footer={
        readOnly ? null : <>
          <Link className="btn btn-ghost" to={`/demands/${demand.id}/chat`}>
            Open chat to edit
          </Link>
          <div className="row-end">
            <Button variant="ghost" onClick={() => load()} disabled={busy || !dirty}>
              Discard changes
            </Button>
            <Button onClick={save} disabled={busy || !dirty || conflict}>
              {busy ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </>
      }
    >
      <div className="stack">
        {!readOnly && <nav className="tabs" aria-label="Demand letter">
          <button className={`tab tab-btn ${tab === 'letter' ? 'active' : ''}`} onClick={() => setTab('letter')}>
            Letter
          </button>
          <button className={`tab tab-btn ${tab === 'details' ? 'active' : ''}`} onClick={() => setTab('details')}>
            Details{dirty ? ' •' : ''}
          </button>
        </nav>}
        {readOnly || tab === 'letter' ? (
          <div className="stack">
            {letter === undefined && <p className="muted">Loading…</p>}
            {letter === null && <p className="muted">No letter generated yet.</p>}
            {letter && (
              <>
                <div className="row-gap">
                  <span className="muted small">
                    Version {letter.version_no} · {formatDateTime(letter.created_at)} · read-only
                  </span>
                  <a className="btn btn-ghost btn-sm" href={`/api/v1/demands/${demand.id}/docx`}>
                    <DownloadIcon /> Download .docx
                  </a>
                </div>
                <div className="drawer-paper">
                  <LetterPreview letter={letter} />
                </div>
              </>
            )}
          </div>
        ) : (
        <div className="stack">
        <div className="row-gap">
          <LifecycleBadge lifecycle={demand.lifecycle} />
          <Badge tone="blue">Status: {demand.progress_status}</Badge>
        </div>

        {conflict && (
          <Alert title="This letter was changed by someone else">
            <span>
              Your changes were not saved.{' '}
              <button className="link-btn" onClick={() => load()}>
                Reload the latest version
              </button>{' '}
              and make your change again.
            </span>
          </Alert>
        )}
        {saved && <Alert tone="success">Saved.</Alert>}
        {error && !error.fieldErrors.length && <ErrorAlert error={error} />}

        <section className="form-grid">
          {FIELDS.map((f) => (
            <Field key={f.key} label={f.label} error={errors[f.key]}>
              {(id) => (
                <input
                  id={id}
                  type={f.type || 'text'}
                  min={f.type === 'number' ? 0 : undefined}
                  value={form[f.key]}
                  onChange={setField(f.key)}
                  maxLength={200}
                />
              )}
            </Field>
          ))}
        </section>

        <section className="stack-sm">
          <div className="section-title">
            <h3>Positions</h3>
            <span className="muted small">
              {trades.length} trade{trades.length === 1 ? '' : 's'} · {tradeTotal} people
            </span>
          </div>
          {trades.length > 0 && (
            <table className="table table-compact trades-table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Trade</th>
                  <th className="num">Qty</th>
                  <th aria-label="Remove" />
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i}>
                    <td>
                      <input aria-label={`Project ${i + 1}`} value={t.project} onChange={(e) => setTrade(i, 'project', e.target.value)} placeholder="optional" />
                    </td>
                    <td>
                      <input aria-label={`Trade ${i + 1}`} value={t.trade} onChange={(e) => setTrade(i, 'trade', e.target.value)} />
                    </td>
                    <td className="num">
                      <input aria-label={`Quantity ${i + 1}`} type="number" min={1} value={t.quantity} onChange={(e) => setTrade(i, 'quantity', e.target.value)} />
                    </td>
                    <td>
                      <button className="icon-btn" aria-label={`Remove row ${i + 1}`} onClick={() => setTrades(trades.filter((_, j) => j !== i))}>
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {errors['0.quantity'] || Object.keys(errors).some((k) => /^\d+\./.test(k)) ? (
            <p className="field-message">Each position needs a trade name and a quantity of at least 1.</p>
          ) : null}
          <div>
            <Button variant="ghost" size="sm" onClick={() => setTrades([...trades, { project: '', trade: '', quantity: '1' }])}>
              + Add position
            </Button>
          </div>
          <p className="muted small">Filled by the AI from the letter. Fields you change here are kept: the AI won't overwrite them.</p>
        </section>
        </div>
        )}
      </div>
    </Drawer>
  )
}
