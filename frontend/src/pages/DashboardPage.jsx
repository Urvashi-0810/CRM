import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { DownloadIcon } from '../components/icons'
import { ErrorAlert, formatDateTime } from '../components/ui'

const PERIODS = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'this_year', label: 'This year' },
  { value: 'custom', label: 'Custom' },
]
const NOT_FILLED = 'Not filled' // letters without an employer/country: gray, not a client
const TOP = 8
// Ordinal ramp (one hue, light → dark) for the ad workflow; validated with the dataviz checks.
const AD_STEPS = { 'Not started': 'var(--viz-step-1)', 'In progress': 'var(--viz-step-2)', Done: 'var(--viz-step-3)' }

const fmt = (n) => Number(n).toLocaleString('en-IN')
const compact = (n) => (n >= 100000 ? `${(n / 100000).toFixed(n >= 1000000 ? 0 : 1)}L` : n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K` : String(n))

function bucketLabel(bucket, unit, long = false) {
  const d = new Date(`${unit === 'day' ? bucket : `${bucket}-01`}T00:00:00`)
  if (unit === 'day') return d.toLocaleDateString('en-GB', long ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' })
  return d.toLocaleDateString('en-GB', long ? { month: 'long', year: 'numeric' } : { month: 'short' })
}

// Clean axis: 3–5 ticks on 1/2/5 steps.
function niceTicks(max) {
  if (max <= 0) return [0, 1]
  const raw = max / 4
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw && s >= 1) || mag
  const ticks = []
  for (let v = 0; v <= max + step * 0.001 || ticks.length < 2; v += step) ticks.push(Math.round(v))
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}

// One floating readout for the whole page, following the pointer (or the focused mark).
function useTooltip() {
  const [tip, setTip] = useState(null)
  const bind = (content) => ({
    onPointerMove: (e) => setTip({ x: e.clientX, y: e.clientY, content }),
    onPointerLeave: () => setTip(null),
    onFocus: (e) => {
      const r = e.currentTarget.getBoundingClientRect()
      setTip({ x: r.right, y: r.top, content })
    },
    onBlur: () => setTip(null),
    tabIndex: 0,
  })
  const node = tip && (
    <div className="viz-tooltip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 240), top: tip.y + 14 }} role="status">
      {tip.content}
    </div>
  )
  return [bind, node]
}

function Tip({ title, rows }) {
  return (
    <>
      <span className="tip-title">{title}</span>
      {rows.map(([value, label]) => (
        <span key={label}>
          <b>{value}</b> {label}
        </span>
      ))}
    </>
  )
}

function Delta({ now, before, vs }) {
  if (before == null || now == null) return <span className="kpi-delta muted">No earlier data to compare</span>
  const diff = now - before
  if (diff === 0) return <span className="kpi-delta muted">No change vs {vs}</span>
  const good = diff > 0
  const pct = before > 0 ? ` (${diff > 0 ? '+' : ''}${Math.round((diff / before) * 100)}%)` : ''
  return (
    <span className="kpi-delta">
      <span className={good ? 'delta-good' : 'delta-bad'} aria-hidden="true">
        {diff > 0 ? '▲' : '▼'}
      </span>{' '}
      {diff > 0 ? '+' : '−'}
      {fmt(Math.abs(diff))}
      {pct} <span className="muted">vs {vs}</span>
    </span>
  )
}

function Kpi({ label, value, children }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {children}
    </div>
  )
}

function Card({ title, subtitle, action, className = '', children }) {
  return (
    <section className={`card dash-card ${className}`}>
      <header className="dash-card-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="muted small">{subtitle}</p>}
        </div>
        {action}
      </header>
      <div className="dash-card-body">{children}</div>
    </section>
  )
}

function Empty({ children = 'No approved orders in this period.' }) {
  return <p className="dash-empty muted">{children}</p>
}

// Columns over time: one series (orders), value axis on the left, the peak labelled.
function ColumnChart({ trend, bind }) {
  const points = trend.points
  const max = Math.max(...points.map((p) => p.orders))
  const ticks = niceTicks(max)
  const top = ticks[ticks.length - 1]
  const every = Math.ceil(points.length / (trend.unit === 'day' ? 8 : 12))
  const peak = points.findIndex((p) => p.orders === max && max > 0)
  return (
    <div className="colchart">
      <div className="colchart-axis" aria-hidden="true">
        {[...ticks].reverse().map((t) => (
          <span key={t}>{compact(t)}</span>
        ))}
      </div>
      <div className="colchart-plot">
        {ticks.map((t) => (
          <span key={t} className="colchart-grid" style={{ bottom: `${(t / top) * 100}%` }} />
        ))}
        <div className="colchart-cols" role="list" aria-label="Orders over time">
          {points.map((p, i) => (
            <div
              key={p.bucket}
              className="colchart-slot"
              role="listitem"
              aria-label={`${bucketLabel(p.bucket, trend.unit, true)}: ${p.orders} orders, ${p.vacancies} vacancies`}
              {...bind(<Tip title={bucketLabel(p.bucket, trend.unit, true)} rows={[[fmt(p.orders), 'orders'], [fmt(p.vacancies), 'vacancies']]} />)}
            >
              {i === peak && <span className="colchart-peak">{fmt(p.orders)}</span>}
              <span className="colchart-col" style={{ height: `${(p.orders / top) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="colchart-x" aria-hidden="true">
          {points.map((p, i) => (
            <span key={p.bucket}>{i % every === 0 ? bucketLabel(p.bucket, trend.unit) : ''}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// Ranked horizontal bars, one series in one hue; value at the tip.
function RankBars({ rows, label, value, tip, bind, unit }) {
  const shown = rows.slice(0, TOP)
  const max = Math.max(1, ...shown.map(value))
  return (
    <div className="rank" role="list">
      {shown.map((row) => (
        <div key={label(row)} className="rank-row" role="listitem" aria-label={`${label(row)}: ${value(row)} ${unit}`} {...bind(tip(row))}>
          <span className="rank-label" title={label(row)}>
            {label(row)}
          </span>
          <span className="rank-track">
            <span className={`rank-bar ${label(row) === NOT_FILLED ? 'rank-bar-muted' : ''}`} style={{ width: `${(value(row) / max) * 100}%` }} />
          </span>
          <span className="rank-value">{fmt(value(row))}</span>
        </div>
      ))}
      {rows.length > TOP && <p className="muted small rank-more">+{rows.length - TOP} more in the Excel export</p>}
    </div>
  )
}

// Part-to-whole at a glance (3 ordered steps): donut with the total in the middle.
function Donut({ parts, bind }) {
  const total = parts.reduce((s, p) => s + p.orders, 0)
  const r = 54
  const c = 2 * Math.PI * r
  const gap = parts.filter((p) => p.orders > 0).length > 1 ? 3 : 0
  let offset = 0
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 140 140" className="donut" role="img" aria-label={parts.map((p) => `${p.status}: ${p.orders}`).join(', ')}>
        <circle cx="70" cy="70" r={r} className="donut-track" />
        {parts.map((p) => {
          if (!p.orders) return null
          const len = (p.orders / total) * c
          const seg = (
            <circle
              key={p.status}
              cx="70"
              cy="70"
              r={r}
              className="donut-seg"
              stroke={AD_STEPS[p.status]}
              strokeDasharray={`${Math.max(len - gap, 1)} ${c}`}
              strokeDashoffset={-offset}
              {...bind(<Tip title={p.status} rows={[[fmt(p.orders), 'orders'], [`${Math.round((p.orders / total) * 100)}%`, 'of all orders']]} />)}
            />
          )
          offset += len
          return seg
        })}
        <text x="70" y="68" className="donut-total">
          {fmt(total)}
        </text>
        <text x="70" y="86" className="donut-caption">
          orders
        </text>
      </svg>
      <ul className="donut-legend">
        {parts.map((p) => (
          <li key={p.status}>
            <span className="legend-key" style={{ background: AD_STEPS[p.status] }} aria-hidden="true" />
            <span className="legend-name">{p.status}</span>
            <strong>{fmt(p.orders)}</strong>
            <span className="muted">{total ? Math.round((p.orders / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function daysSince(iso) {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
}

export default function DashboardPage() {
  const [params, setParams] = useSearchParams()
  const period = params.get('period') || 'this_month'
  const [from, setFrom] = useState(params.get('date_from') || '')
  const [to, setTo] = useState(params.get('date_to') || '')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [bind, tooltip] = useTooltip()

  const query = useMemo(() => {
    const q = new URLSearchParams({ period })
    if (period === 'custom') {
      if (params.get('date_from')) q.set('date_from', params.get('date_from'))
      if (params.get('date_to')) q.set('date_to', params.get('date_to'))
    }
    return q
  }, [params, period])
  const customIncomplete = period === 'custom' && !(params.get('date_from') && params.get('date_to'))

  useEffect(() => {
    if (customIncomplete) return
    setLoading(true)
    api(`/dashboard?${query}`)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [query, customIncomplete])

  function setPeriod(value, nextFrom = from, nextTo = to) {
    const next = new URLSearchParams({ period: value })
    if (value === 'custom') {
      if (nextFrom) next.set('date_from', nextFrom)
      if (nextTo) next.set('date_to', nextTo)
    }
    setParams(next, { replace: true })
  }

  const show = data && !customIncomplete
  const t = data?.totals
  const pt = data?.previous_totals
  const vs = data?.previous.label
  const none = show && t.orders === 0

  return (
    <div className="page viz-root dashboard">
      <div className="dash-top">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="muted small">
            {show ? `${data.period.label} · ` : ''}Approved demand letters (1 letter = 1 order), by approval date, India time.
            {loading && show ? ' Updating…' : ''}
          </p>
        </div>
        <div className="dash-controls">
          <div className="segmented" role="group" aria-label="Period">
            {PERIODS.map((p) => (
              <button key={p.value} className={period === p.value ? 'active' : ''} onClick={() => setPeriod(p.value)} aria-pressed={period === p.value}>
                {p.label}
              </button>
            ))}
          </div>
          {period === 'custom' && (
            <div className="date-range" role="group" aria-label="Custom date range">
              <input
                type="date"
                aria-label="From"
                value={from}
                max={to || undefined}
                onChange={(e) => {
                  setFrom(e.target.value)
                  setPeriod('custom', e.target.value, to)
                }}
              />
              <span>to</span>
              <input
                type="date"
                aria-label="To"
                value={to}
                min={from || undefined}
                onChange={(e) => {
                  setTo(e.target.value)
                  setPeriod('custom', from, e.target.value)
                }}
              />
            </div>
          )}
          {show && (
            <a className="btn btn-ghost btn-sm" href={`/api/v1/dashboard/export?${query}`} download>
              <DownloadIcon /> Export
            </a>
          )}
        </div>
      </div>

      <ErrorAlert error={error} />
      {customIncomplete && <p className="muted">Choose a start and an end date.</p>}

      {show && (
        <>
          <div className="kpi-row">
            <Kpi label="Orders" value={fmt(t.orders)}>
              <Delta now={t.orders} before={pt.orders} vs={vs} />
            </Kpi>
            <Kpi label="Vacancies" value={fmt(t.vacancies)}>
              <Delta now={t.vacancies} before={pt.vacancies} vs={vs} />
            </Kpi>
            <Kpi label="Clients" value={fmt(t.clients)}>
              <Delta now={t.clients} before={pt.clients} vs={vs} />
            </Kpi>
            <Kpi label="New clients" value={fmt(t.new_clients)}>
              <Delta now={t.new_clients} before={pt.new_clients} vs={vs} />
            </Kpi>
          </div>

          <div className="dash-grid">
            <Card title="Orders over time" subtitle={`Approved letters per ${data.trend.unit}. Hover for vacancies.`} className="span-2">
              {none ? <Empty /> : <ColumnChart trend={data.trend} bind={bind} />}
            </Card>

            <Card title="Pipeline right now" subtitle="Not limited to the period.">
              <ul className="pipeline">
                <li>
                  <span className="pipeline-num">{fmt(data.pipeline.drafts)}</span>
                  <span>Drafts in progress</span>
                </li>
                <li>
                  <span className="pipeline-num">{fmt(data.pipeline.waiting_approval)}</span>
                  <span>
                    Waiting for admin approval
                    {data.pipeline.oldest_waiting_since && (
                      <span className="muted small pipeline-note">
                        Oldest waiting {daysSince(data.pipeline.oldest_waiting_since) || 'under 1'} day
                        {daysSince(data.pipeline.oldest_waiting_since) === 1 ? '' : 's'} (since {formatDateTime(data.pipeline.oldest_waiting_since)})
                      </span>
                    )}
                  </span>
                </li>
                <li>
                  <span className="pipeline-num">{fmt(data.pipeline.approved_all_time)}</span>
                  <span>Approved, all time</span>
                </li>
              </ul>
              <Link to="/demands" className="link-btn pipeline-link">
                Open the demand list →
              </Link>
            </Card>

            <Card title="Top clients" subtitle="Orders per employer.">
              {none ? (
                <Empty />
              ) : (
                <RankBars
                  rows={data.by_client}
                  label={(c) => c.employer}
                  value={(c) => c.orders}
                  unit="orders"
                  bind={bind}
                  tip={(c) => <Tip title={c.employer} rows={[[fmt(c.orders), 'orders'], [fmt(c.vacancies), 'vacancies']]} />}
                />
              )}
            </Card>

            <Card title="Orders by country" subtitle="Where the jobs are.">
              {none ? (
                <Empty />
              ) : (
                <RankBars
                  rows={data.by_country}
                  label={(c) => c.country}
                  value={(c) => c.orders}
                  unit="orders"
                  bind={bind}
                  tip={(c) => <Tip title={c.country} rows={[[fmt(c.orders), 'orders'], [fmt(c.vacancies), 'vacancies']]} />}
                />
              )}
            </Card>

            <Card title="Repeat clients" subtitle="2 or more orders in the same month.">
              {none ? (
                <Empty />
              ) : data.repeat_clients.length === 0 ? (
                <Empty>No client ordered twice in one month in this period.</Empty>
              ) : (
                <ul className="repeat-list">
                  {data.repeat_clients.slice(0, TOP).map((c) => (
                    <li key={c.employer}>
                      <span className="repeat-name" title={c.employer}>
                        {c.employer}
                      </span>
                      <span className="repeat-count">
                        {c.repeat_months} {c.repeat_months === 1 ? 'month' : 'months'}
                      </span>
                      <span className="muted small repeat-months">
                        {c.months.map((m) => `${bucketLabel(m.month, 'month', true)} (${m.orders})`).join(' · ')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Most demanded positions" subtitle="People needed, across the period's orders.">
              {data.positions.length === 0 ? (
                <Empty>{none ? undefined : 'No positions recorded on these orders.'}</Empty>
              ) : (
                <RankBars
                  rows={data.positions}
                  label={(p) => p.position}
                  value={(p) => p.people}
                  unit="people"
                  bind={bind}
                  tip={(p) => <Tip title={p.position} rows={[[fmt(p.people), 'people needed'], [fmt(p.orders), p.orders === 1 ? 'order' : 'orders']]} />}
                />
              )}
            </Card>

            <Card title="Advertisement status" subtitle="Progress on the period's orders.">
              {none ? <Empty /> : <Donut parts={data.ad_status} bind={bind} />}
            </Card>

            <Card title="Team output" subtitle="Approved letters per creator.">
              {data.team.length === 0 ? (
                <Empty />
              ) : (
                <RankBars
                  rows={data.team}
                  label={(m) => m.name}
                  value={(m) => m.orders}
                  unit="approved letters"
                  bind={bind}
                  tip={(m) => <Tip title={m.name} rows={[[fmt(m.orders), 'approved letters'], [fmt(m.vacancies), 'vacancies']]} />}
                />
              )}
            </Card>
          </div>
        </>
      )}
      {tooltip}
    </div>
  )
}
