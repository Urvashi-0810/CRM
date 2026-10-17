import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadFile } from '../api/client'
import DemandDrawer from '../components/DemandDrawer'
import { DownloadIcon, SearchIcon } from '../components/icons'
import { Button, ErrorAlert, Modal, Pagination, formatDate, formatDateTime, useDebounced } from '../components/ui'

const FILTER_KEYS = ['q', 'country', 'employer', 'ad_status', 'ad_assigned_to', 'approved_from', 'approved_to']
const DEFAULT_LIMIT = 25
const AD_STATUS_TONE = { 'Not started': 'amber', 'In progress': 'blue', Done: 'green' }

const TOOLS = {
  canva: {
    label: 'Canva',
    site: 'https://www.canva.com/',
    formats: [
      { value: 'docx', label: 'Word (.docx)', hint: 'Canva imports it as an editable design' },
      { value: 'pdf', label: 'PDF', hint: 'Keeps the exact layout' },
    ],
  },
  figma: {
    label: 'Figma',
    site: 'https://www.figma.com/',
    formats: [
      { value: 'png', label: 'PNG', hint: 'One image per page, sharp text' },
      { value: 'jpg', label: 'JPG', hint: 'One image per page, smaller files' },
    ],
  },
}

// Step 1: Canva or Figma. Step 2: the format. The newest version of the letter downloads;
// the person then drags it into the tool.
function ExportDialog({ demand, onClose }) {
  const [tool, setTool] = useState(null)
  const [busyFormat, setBusyFormat] = useState(null)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState(null)

  async function download(format) {
    setBusyFormat(format)
    setError(null)
    setSaved(null)
    try {
      setSaved(await downloadFile(`/ads/${demand.id}/export?tool=${tool}&format=${format}`))
    } catch (err) {
      setError(err)
    } finally {
      setBusyFormat(null)
    }
  }

  return (
    <Modal title={`Export ${demand.demand_code}`} onClose={onClose}>
      <div className="stack">
        <p className="muted small">Uses the newest version of the letter (v{demand.latest_version_no}), including edits made after approval.</p>
        <div>
          <p className="export-step">1. Where will you design the ad?</p>
          <div className="export-choices">
            {Object.entries(TOOLS).map(([key, t]) => (
              <button
                key={key}
                type="button"
                className={`export-choice ${tool === key ? 'active' : ''}`}
                onClick={() => {
                  setTool(key)
                  setSaved(null)
                  setError(null)
                }}
                aria-pressed={tool === key}
              >
                <strong>{t.label}</strong>
              </button>
            ))}
          </div>
        </div>
        {tool && (
          <div>
            <p className="export-step">2. Choose the format</p>
            <div className="export-choices">
              {TOOLS[tool].formats.map((f) => (
                <button key={f.value} type="button" className="export-choice" onClick={() => download(f.value)} disabled={Boolean(busyFormat)}>
                  <strong>{busyFormat === f.value ? 'Preparing…' : f.label}</strong>
                  <span className="muted small">{f.hint}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <ErrorAlert error={error} />
        {saved && (
          <div className="alert alert-success" role="status">
            <span>
              Downloaded <strong>{saved}</strong>.{' '}
              <a href={TOOLS[tool].site} target="_blank" rel="noreferrer">
                Open {TOOLS[tool].label} ↗
              </a>{' '}
              and drag the file in.
              {saved.endsWith('.zip') && ' The letter has several pages: unzip it first, there is one image per page.'}
            </span>
          </div>
        )}
      </div>
    </Modal>
  )
}

// Who the ad is assigned to: free text, saved when the field loses focus or on Enter.
function AssigneeCell({ demand, suggestions, onSave }) {
  const [value, setValue] = useState(demand.ad_assigned_to || '')
  useEffect(() => setValue(demand.ad_assigned_to || ''), [demand.ad_assigned_to])

  function commit() {
    if (value.trim() !== (demand.ad_assigned_to || '')) onSave({ ad_assigned_to: value.trim() })
  }

  return (
    <input
      className="cell-input"
      value={value}
      maxLength={200}
      list="ad-assignees"
      placeholder="Unassigned"
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') setValue(demand.ad_assigned_to || '')
      }}
      aria-label={`Ad assigned to, ${demand.demand_code}`}
      title={suggestions.length ? 'Type a name or pick one used before' : 'Type a name'}
    />
  )
}

export default function AdvertisementsPage() {
  // Filters, sort and page live in the URL, so refresh/back keep them.
  const [params, setParams] = useSearchParams()
  const [searchText, setSearchText] = useState(params.get('q') || '')
  const debouncedSearch = useDebounced(searchText, 300)

  const [page, setPage] = useState({ items: [], total: 0, limit: DEFAULT_LIMIT, offset: 0 })
  const [options, setOptions] = useState({ countries: [], employers: [], ad_statuses: [], ad_assignees: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [exporting, setExporting] = useState(null)
  const [savingId, setSavingId] = useState(null)

  const sort = params.get('sort') || '-approved_at'
  const limit = Number(params.get('limit')) || DEFAULT_LIMIT
  const offset = Number(params.get('offset')) || 0

  const filterQuery = useMemo(() => {
    const q = new URLSearchParams()
    for (const key of FILTER_KEYS) {
      const v = params.get(key)
      if (v) q.set(key, v)
    }
    q.set('sort', sort)
    return q
  }, [params, sort])

  function updateParams(changes, { resetPage = true } = {}) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v === '' || v == null) next.delete(k)
      else next.set(k, String(v))
    }
    if (resetPage) next.delete('offset')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if ((params.get('q') || '') !== debouncedSearch) updateParams({ q: debouncedSearch })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch])

  const loadList = useCallback(async () => {
    const q = new URLSearchParams(filterQuery)
    q.set('limit', limit)
    q.set('offset', offset)
    setPage(await api(`/ads?${q}`))
  }, [filterQuery, limit, offset])

  const loadOptions = useCallback(async () => {
    setOptions(await api('/ads/filter-options'))
  }, [])

  useEffect(() => {
    setLoading(true)
    loadList()
      .then(() => setError(null))
      .catch(setError)
      .finally(() => setLoading(false))
  }, [loadList])

  useEffect(() => {
    loadOptions().catch(() => {})
  }, [loadOptions])

  async function saveAd(demand, changes) {
    setSavingId(demand.id)
    setError(null)
    try {
      const updated = await api(`/ads/${demand.id}`, { method: 'PATCH', body: changes })
      setPage((current) => ({ ...current, items: current.items.map((d) => (d.id === updated.id ? updated : d)) }))
      if ('ad_assigned_to' in changes) loadOptions().catch(() => {})
    } catch (err) {
      setError(err)
    } finally {
      setSavingId(null)
    }
  }

  function toggleSort(field) {
    updateParams({ sort: sort === `-${field}` ? field : `-${field}` })
  }

  function sortMark(field) {
    if (sort === field) return ' ▲'
    if (sort === `-${field}`) return ' ▼'
    return ''
  }

  const hasFilters = FILTER_KEYS.some((k) => params.get(k))
  const exportHref = `/api/v1/ads/export?${filterQuery}`

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Create Advertisement</h1>
      </div>
      <p className="muted small page-intro">
        Approved demand letters, ready to turn into ads. Export a letter for Canva or Figma, then track the ad here. Letters
        can't be changed from this page.
      </p>

      <ErrorAlert error={error} />

      <section className="card filters-card">
        <div className="search-box">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search by demand ID, employer, country…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            aria-label="Search"
          />
        </div>
        <div className="filters-row">
          <select value={params.get('country') || ''} onChange={(e) => updateParams({ country: e.target.value })} aria-label="Country">
            <option value="">All countries</option>
            {options.countries.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <select value={params.get('employer') || ''} onChange={(e) => updateParams({ employer: e.target.value })} aria-label="Employer">
            <option value="">All employers</option>
            {options.employers.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <select value={params.get('ad_assigned_to') || ''} onChange={(e) => updateParams({ ad_assigned_to: e.target.value })} aria-label="Ad assigned to">
            <option value="">Anyone assigned</option>
            {options.ad_assignees.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <select value={params.get('ad_status') || ''} onChange={(e) => updateParams({ ad_status: e.target.value })} aria-label="Ad status">
            <option value="">All ad statuses</option>
            {options.ad_statuses.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <div className="date-range" role="group" aria-label="Approved date range">
            <span>Approved</span>
            <input type="date" aria-label="Approved from" value={params.get('approved_from') || ''} onChange={(e) => updateParams({ approved_from: e.target.value })} />
            <span>to</span>
            <input type="date" aria-label="Approved to" value={params.get('approved_to') || ''} onChange={(e) => updateParams({ approved_to: e.target.value })} />
          </div>
          {hasFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearchText('')
                updateParams(Object.fromEntries(FILTER_KEYS.map((k) => [k, ''])))
              }}
            >
              Clear filters
            </Button>
          )}
          <a className="btn btn-ghost btn-sm export-btn" href={exportHref} download>
            <DownloadIcon /> Export to Excel
          </a>
        </div>
      </section>

      <datalist id="ad-assignees">
        {options.ad_assignees.map((a) => (
          <option key={a} value={a} />
        ))}
      </datalist>

      <section className="card">
        <div className="table-wrap">
          <table className="table demand-table">
            <thead>
              <tr>
                <th>
                  <button className="sort-btn" onClick={() => toggleSort('approved_at')}>
                    Approved on{sortMark('approved_at')}
                  </button>
                </th>
                <th>
                  <button className="sort-btn" onClick={() => toggleSort('country')}>
                    Country{sortMark('country')}
                  </button>
                </th>
                <th>
                  <button className="sort-btn" onClick={() => toggleSort('demand_code')}>
                    Demand ID{sortMark('demand_code')}
                  </button>
                </th>
                <th>
                  <button className="sort-btn" onClick={() => toggleSort('employer')}>
                    Employer{sortMark('employer')}
                  </button>
                </th>
                <th className="num">
                  <button className="sort-btn" onClick={() => toggleSort('vacancy')}>
                    Vacancy{sortMark('vacancy')}
                  </button>
                </th>
                <th>Target timeline</th>
                <th>Ad assigned to</th>
                <th>Ad status</th>
                <th className="center">Download</th>
                <th className="center">Export</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => setOpenId(d.id)}>
                  <td className="num">{formatDate(d.approved_at)}</td>
                  <td>{d.country ? <span className="pill">{d.country}</span> : <span className="muted">—</span>}</td>
                  <td className="code">{d.demand_code}</td>
                  <td>{d.employer || <span className="muted">—</span>}</td>
                  <td className="num">{d.vacancy ?? <span className="muted">—</span>}</td>
                  <td>{d.target_timeline || <span className="muted">—</span>}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <AssigneeCell demand={d} suggestions={options.ad_assignees} onSave={(changes) => saveAd(d, changes)} />
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <select
                      className={`ad-status ad-status-${AD_STATUS_TONE[d.ad_status] || 'amber'}`}
                      value={d.ad_status}
                      onChange={(e) => saveAd(d, { ad_status: e.target.value })}
                      disabled={savingId === d.id}
                      aria-label={`Ad status, ${d.demand_code}`}
                      title={d.ad_updated_by ? `Changed by ${d.ad_updated_by.display_name}, ${formatDateTime(d.ad_updated_at)}` : 'Not changed yet'}
                    >
                      {options.ad_statuses.map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  </td>
                  <td className="center" onClick={(e) => e.stopPropagation()}>
                    {d.latest_version_no ? (
                      <a className="icon-action" href={`/api/v1/demands/${d.id}/docx`} title={`Download version ${d.latest_version_no} (.docx)`} aria-label={`Download ${d.demand_code}`}>
                        <DownloadIcon />
                      </a>
                    ) : (
                      <button className="icon-action" disabled title="No letter generated yet" aria-label={`No letter for ${d.demand_code}`}>
                        <DownloadIcon />
                      </button>
                    )}
                  </td>
                  <td className="center" onClick={(e) => e.stopPropagation()}>
                    <Button variant="ghost" size="sm" onClick={() => setExporting(d)} disabled={!d.latest_version_no}>
                      Export
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && page.items.length === 0 && (
            <div className="empty">
              {hasFilters ? 'No approved letters match these filters.' : 'No approved demand letters yet. They appear here once an admin approves them.'}
            </div>
          )}
        </div>
        <Pagination
          total={page.total}
          limit={limit}
          offset={offset}
          onChange={(o) => updateParams({ offset: o || '' }, { resetPage: false })}
          onLimitChange={(l) => updateParams({ limit: l === DEFAULT_LIMIT ? '' : l })}
        />
      </section>

      {openId && <DemandDrawer demandId={openId} onClose={() => setOpenId(null)} readOnly />}
      {exporting && <ExportDialog demand={exporting} onClose={() => setExporting(null)} />}
    </div>
  )
}
