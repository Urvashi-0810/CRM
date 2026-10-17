import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { ChatIcon, TrashIcon } from './icons'
import { Button, ConfirmModal, ErrorAlert, formatDateTime } from './ui'

// "Yet to be approved" drafts, shown above the demand list.
export default function DraftsSection({ drafts, total, onChanged }) {
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function confirmDelete() {
    setBusy(true)
    setError(null)
    try {
      await api(`/demands/${deleting.id}`, { method: 'DELETE' })
      setDeleting(null)
      onChanged()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (!total) return null

  return (
    <section className="drafts">
      <header className="drafts-header">
        <h2>Yet to be approved</h2>
        <span className="count-pill">{total}</span>
      </header>
      <ul className="drafts-list">
        {drafts.map((d) => (
          <li key={d.id} className="draft-card">
            <div className="draft-main">
              <span className="code">{d.demand_code}</span>
              <span className="muted small">
                {d.employer || 'No employer yet'}
                {d.country ? ` · ${d.country}` : ''}
              </span>
              <span className="muted small">
                Started {formatDateTime(d.created_at)} by {d.created_by.display_name}
                {d.latest_version_no ? ` · letter v${d.latest_version_no}` : ''}
              </span>
            </div>
            <div className="draft-actions">
              <Button size="sm" onClick={() => navigate(`/demands/${d.id}/chat`)}>
                <ChatIcon /> Continue chat
              </Button>
              <Button variant="danger" size="sm" onClick={() => setDeleting(d)} aria-label={`Delete draft ${d.demand_code}`}>
                <TrashIcon />
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {total > drafts.length && <p className="muted small">Showing the {drafts.length} newest of {total} drafts.</p>}
      {deleting && (
        <ConfirmModal
          title={`Delete draft ${deleting.demand_code}?`}
          confirmLabel="Delete draft"
          danger
          busy={busy}
          onConfirm={confirmDelete}
          onClose={() => {
            setDeleting(null)
            setError(null)
          }}
        >
          <p>
            The draft, its chat and its files are deleted permanently. The ID <strong>{deleting.demand_code}</strong>{' '}
            becomes free and will be given to the next new letter.
          </p>
          <ErrorAlert error={error} />
        </ConfirmModal>
      )}
    </section>
  )
}
