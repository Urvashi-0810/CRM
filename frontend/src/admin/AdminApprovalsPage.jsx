import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Alert, Button, Card, formatDateTime } from '../components/ui'
import { useAdmin } from './AdminGate'

// Letters sent for approval. The admin opens each one, checks the letter, and approves
// it or sends it back from the letter's page.
export default function AdminApprovalsPage() {
  const { handleError } = useAdmin()
  const navigate = useNavigate()
  const [page, setPage] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      setPage(await api('/demands?lifecycle=pending&sort=submitted_at&limit=200'))
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [handleError])

  useEffect(() => {
    load()
  }, [load])

  return (
    <Card title={`Letters waiting for approval${page ? ` (${page.total})` : ''}`}>
      {error && <Alert title={error.title}>{error.message !== error.title ? error.message : null}</Alert>}
      {!page ? (
        <p className="muted">Loading…</p>
      ) : page.items.length === 0 ? (
        <p className="muted">No letters waiting for approval.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Sent</th>
              <th>Demand ID</th>
              <th>Employer</th>
              <th>Country</th>
              <th>Created by</th>
              <th>Sent by</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {page.items.map((d) => (
              <tr key={d.id}>
                <td className="num">{formatDateTime(d.submitted_at)}</td>
                <td className="code">{d.demand_code}</td>
                <td>{d.employer || <span className="muted">—</span>}</td>
                <td>{d.country || <span className="muted">—</span>}</td>
                <td>{d.created_by.display_name}</td>
                <td>{d.submitted_by?.display_name}</td>
                <td className="row-actions">
                  <Button size="sm" onClick={() => navigate(`/demands/${d.id}/chat`)}>
                    Review letter
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
