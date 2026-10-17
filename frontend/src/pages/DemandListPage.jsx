import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import DemandDrawer from '../components/DemandDrawer'
import DraftsSection from '../components/DraftsSection'
import { DownloadIcon, EditIcon, SearchIcon } from '../components/icons'
import { Badge, Button, ErrorAlert, Pagination, formatDate, newRequestKey } from '../components/ui'

const FILTER_KEYS = ['q', 'country', 'employer', 'progress_status', 'assign_to', 'approved_from', 'approved_to']
const DEFAULT_LIMIT = 25

function useDebounced(value, ms) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

export default function DemandListPage() {
  const navigate = useNavigate()
  // Filters, sort and page live in the URL, so refresh/back keep them.
  const [params, setParams] = useSearchParams()
  const [searchText, setSearchText] = useState(params.get('q') || '')
  const debouncedSearch = useDebounced(searchText, 300)

  const [page, setPage] = useState({ items: [], total: 0, limit: DEFAULT_LIMIT, offset: 0 })
  const [drafts, setDrafts] = useState({ items: [], total: 0 })
  const [pending, setPending] = useState({ items: [], total: 0 })
  const [options, setOptions] = useState({ countries: [], employers: [], assignees: [], statuses: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [openId, setOpenId] = useState(null)
  const addKey = useRef(null)

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
    setPage(await api(`/demands?${q}`))
  }, [filterQuery, limit, offset])

  const loadDrafts = useCallback(async () => {
    const [draftPage, pendingPage] = await Promise.all([
      api('/demands?lifecycle=draft&sort=-created_at&limit=50'),
      api('/demands?lifecycle=pending&sort=-submitted_at&limit=50'),
    ])
    setDrafts(draftPage)
    setPending(pendingPage)
  }, [])

  const loadOptions = useCallback(async () => {
    setOptions(await api('/demands/filter-options'))
  }, [])

  useEffect(() => {
    setLoading(true)
    loadList()
      .then(() => setError(null))
      .catch(setError)
      .finally(() => setLoading(false))
  }, [loadList])

  useEffect(() => {
    loadDrafts().catch(setError)
    loadOptions().catch(() => {})
  }, [loadDrafts, loadOptions])

  async function addDemandLetter() {
    setAdding(true)
    setError(null)
    // One key per click: a double click or a retry gets the same draft back.
    addKey.current = addKey.current || newRequestKey()
    try {
      const demand = await api('/demands', { method: 'POST', headers: { 'Idempotency-Key': addKey.current } })
      addKey.current = null
      navigate(`/demands/${demand.id}/chat`)
    } catch (err) {
      if (err.status !== 0) addKey.current = null // network error: keep the key for the retry
      setError(err)
    } finally {
      setAdding(false)
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
  const exportHref = `/api/v1/demands/export?${filterQuery}`

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Demand Drafts</h1>
        <Button onClick={addDemandLetter} disabled={adding}>
          {adding ? 'Reserving ID…' : '+ Add Demand Letter'}
        </Button>
      </div>

      <ErrorAlert error={error} />

      <DraftsSection
        drafts={drafts.items}
        total={drafts.total}
        pending={pending.items}
        pendingTotal={pending.total}
        onChanged={() => {
          loadDrafts()
          loadOptions()
        }}
      />

      <section className="card filters-card">
        <div className="search-box">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search by demand ID, employer, country, assignee…"
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
          <select value={params.get('assign_to') || ''} onChange={(e) => updateParams({ assign_to: e.target.value })} aria-label="Assigned to">
            <option value="">Anyone assigned</option>
            {options.assignees.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <select value={params.get('progress_status') || ''} onChange={(e) => updateParams({ progress_status: e.target.value })} aria-label="Status">
            <option value="">All statuses</option>
            {options.statuses.map((c) => (
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

      <section className="card">
        <div className="table-wrap">
          <table className="table demand-table">
            <thead>
              <tr>
                <th>
                  <button className="sort-btn" onClick={() => toggleSort('approved_at')}>
                    Approved date{sortMark('approved_at')}
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
                <th>Assign to</th>
                <th>Status</th>
                <th className="center">File</th>
                <th className="center">Edit</th>
                <th>Created by</th>
                <th>Approved by</th>
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
                  <td>{d.assign_to || <span className="muted">—</span>}</td>
                  <td>
                    <Badge tone="blue">{d.progress_status}</Badge>
                  </td>
                  <td className="center" onClick={(e) => e.stopPropagation()}>
                    {d.latest_version_no ? (
                      <a className="icon-action" href={`/api/v1/demands/${d.id}/docx`} title={`Download version ${d.latest_version_no}`} aria-label={`Download ${d.demand_code}`}>
                        <DownloadIcon />
                      </a>
                    ) : (
                      <button className="icon-action" disabled title="No letter generated yet" aria-label={`No letter for ${d.demand_code}`}>
                        <DownloadIcon />
                      </button>
                    )}
                  </td>
                  <td className="center" onClick={(e) => e.stopPropagation()}>
                    <button className="icon-action" title="Open the letter's chat" aria-label={`Edit ${d.demand_code}`} onClick={() => navigate(`/demands/${d.id}/chat`)}>
                      <EditIcon />
                    </button>
                  </td>
                  <td>{d.created_by.display_name}</td>
                  <td>{d.approved_by?.display_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && page.items.length === 0 && (
            <div className="empty">
              {hasFilters ? 'No demand letters match these filters.' : 'No approved demand letters yet. Approved letters appear here.'}
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

      {openId && (
        <DemandDrawer
          demandId={openId}
          onClose={() => setOpenId(null)}
          onSaved={() => {
            loadList()
            loadOptions()
          }}
        />
      )}
    </div>
  )
}
