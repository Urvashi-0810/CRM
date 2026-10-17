import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Alert, Button, Card, ErrorAlert, Field, fieldErrorsOf } from '../components/ui'
import { useAdmin } from './AdminGate'

const usd = (v) => (v == null ? '—' : `$${Number(v).toFixed(2)}`)
const num = (v) => new Intl.NumberFormat('en-IN').format(v)

function thisMonth() {
  return new Date().toISOString().slice(0, 7) // UTC month, like the cap
}

export default function AdminUsagePage() {
  const { handleError } = useAdmin()
  const [month, setMonth] = useState(thisMonth())
  const [usage, setUsage] = useState(null)
  const [cap, setCap] = useState(null)
  const [form, setForm] = useState({ enabled: false, monthly_usd: '' })
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [u, c] = await Promise.all([api(`/admin/usage?month=${month}`), api('/admin/spend-cap')])
      setUsage(u)
      setCap(c)
      setForm({ enabled: c.enabled, monthly_usd: c.monthly_usd ?? '' })
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [month, handleError])

  useEffect(() => {
    load()
  }, [load])

  async function saveCap(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      const body = { enabled: form.enabled }
      if (form.monthly_usd !== '') body.monthly_usd = form.monthly_usd
      await api('/admin/spend-cap', { method: 'PUT', body })
      setSaved(true)
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  const spent = cap ? Number(cap.spent_this_month_usd) : 0
  const limit = cap?.monthly_usd ? Number(cap.monthly_usd) : null
  const fraction = limit ? Math.min(spent / limit, 1) : 0
  const maxDay = usage ? Math.max(0.0001, ...usage.by_day.map((d) => Number(d.cost_usd))) : 1

  return (
    <div className="stack">
      <Card title="Monthly AI budget">
        <p className="muted small">
          When the limit is reached, new chat messages are refused with a clear message until the month ends. Months follow
          UTC, like the AI provider’s billing (the 1st, 00:00 UTC = 05:30 India time).
        </p>
        {error && !error.fieldErrors?.length && <ErrorAlert error={error} />}
        {saved && <Alert tone="success">Saved.</Alert>}
        {cap && (
          <div className="stack">
            <div className="usage-grid">
              <div className="stat">
                <div className="label">Spent this month</div>
                <div className="value">{usd(spent)}</div>
              </div>
              <div className="stat">
                <div className="label">Limit</div>
                <div className="value">{cap.enabled && limit != null ? usd(limit) : 'Off'}</div>
              </div>
            </div>
            {cap.enabled && limit != null && (
              <div className={`meter ${spent >= limit ? 'over' : ''}`} role="img" aria-label={`${Math.round(fraction * 100)}% of the limit used`}>
                <span style={{ width: `${fraction * 100}%` }} />
              </div>
            )}
          </div>
        )}
        <form className="inline-form" onSubmit={saveCap}>
          <label className="checkbox">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Limit
            monthly AI spend
          </label>
          <Field label="Monthly limit (USD)" error={fieldErrorsOf(error).monthly_usd}>
            {(id) => (
              <input id={id} type="number" min="0" step="0.01" value={form.monthly_usd}
                onChange={(e) => setForm({ ...form, monthly_usd: e.target.value })} disabled={!form.enabled} />
            )}
          </Field>
          <Button type="submit" disabled={busy}>
            Save
          </Button>
        </form>
      </Card>

      <Card
        title="Usage"
        actions={
          <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} aria-label="Month" className="month-input" />
        }
      >
        {usage && (
          <>
            <div className="usage-grid">
              <div className="stat">
                <div className="label">Cost</div>
                <div className="value">{usd(usage.total_cost_usd)}</div>
              </div>
              <div className="stat">
                <div className="label">AI calls</div>
                <div className="value">{num(usage.calls)}</div>
              </div>
              <div className="stat">
                <div className="label">Successful</div>
                <div className="value">{num(usage.successful_calls)}</div>
              </div>
            </div>
            {usage.unpriced_calls > 0 && (
              <Alert tone="info">
                {usage.unpriced_calls} call(s) used a model without a known price, so their cost is not included.
              </Alert>
            )}
            {usage.by_day.some((d) => Number(d.cost_usd) > 0) && (
              <div>
                <div className="muted small">Cost per day (UTC)</div>
                <div className="day-bars">
                  {usage.by_day.map((d) => (
                    <span key={d.day} title={`${d.day}: ${usd(d.cost_usd)} · ${d.calls} calls`} style={{ height: `${(Number(d.cost_usd) / maxDay) * 100}%` }} />
                  ))}
                </div>
              </div>
            )}
            {usage.by_model.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Model</th>
                    <th className="num">Calls</th>
                    <th className="num">Input tokens</th>
                    <th className="num">Cached input</th>
                    <th className="num">Output tokens</th>
                    <th className="num">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.by_model.map((m) => (
                    <tr key={`${m.provider}-${m.model}`}>
                      <td>{m.provider}</td>
                      <td className="mono">{m.model}</td>
                      <td className="num">{num(m.calls)}</td>
                      <td className="num">{num(m.input_tokens)}</td>
                      <td className="num">{num(m.cache_read_tokens)}</td>
                      <td className="num">{num(m.output_tokens)}</td>
                      <td className="num">{usd(m.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No AI calls in this month.</p>
            )}
          </>
        )}
      </Card>
    </div>
  )
}
