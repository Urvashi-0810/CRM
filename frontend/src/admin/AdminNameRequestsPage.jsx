import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Button, Card, formatDateTime } from '../components/ui'
import { useAdmin } from './AdminGate'

const FILTERS = [
  { value: 'pending', label: 'Pending' },
  { value: '', label: 'All' },
]
const STATUS_TONE = { pending: 'amber', approved: 'green', rejected: 'red' }

export default function AdminNameRequestsPage() {
  const { handleError } = useAdmin()
  const { refresh } = useAuth()
  const [filter, setFilter] = useState('pending')
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(async () => {
    try {
      const query = filter ? `?status=${filter}` : ''
      setItems((await api(`/admin/name-change-requests${query}`)).items)
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [filter, handleError])

  useEffect(() => {
    load()
  }, [load])

  async function review(item, action) {
    setBusyId(item.id)
    setError(null)
    try {
      await api(`/admin/name-change-requests/${item.id}/${action}`, { method: 'POST' })
      // The approved request may be the admin's own; refresh the sidebar name too.
      await Promise.all([load(), refresh()])
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Card
      title="Name-change requests"
      actions={
        <div className="segmented" role="group" aria-label="Filter">
          {FILTERS.map((f) => (
            <button key={f.label} className={filter === f.value ? 'active' : ''} onClick={() => setFilter(f.value)}>
              {f.label}
            </button>
          ))}
        </div>
      }
    >
      {error && <Alert title={error.title}>{error.message !== error.title ? error.message : null}</Alert>}
      {items.length === 0 ? (
        <p className="muted">{filter === 'pending' ? 'No requests waiting for approval.' : 'No requests yet.'}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Requested</th>
              <th>Current name</th>
              <th>New name</th>
              <th>Status</th>
              <th>Reviewed by</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td className="num">{formatDateTime(r.created_at)}</td>
                <td>
                  {r.current_name} <span className="muted small mono">@{r.username}</span>
                </td>
                <td>
                  <strong>{r.requested_name}</strong>
                </td>
                <td>
                  <Badge tone={STATUS_TONE[r.status]}>{r.status[0].toUpperCase() + r.status.slice(1)}</Badge>
                </td>
                <td>{r.reviewed_by_name || <span className="muted">—</span>}</td>
                <td className="row-actions">
                  {r.status === 'pending' && (
                    <>
                      <Button size="sm" disabled={busyId === r.id} onClick={() => review(r, 'approve')}>
                        Approve
                      </Button>
                      <Button variant="danger" size="sm" disabled={busyId === r.id} onClick={() => review(r, 'reject')}>
                        Reject
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
