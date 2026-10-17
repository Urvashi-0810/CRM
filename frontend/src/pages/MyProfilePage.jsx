import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Alert, Badge, Button, Card, Field, fieldErrorsOf, formatDateTime } from '../components/ui'

const STATUS_TONE = { pending: 'amber', approved: 'green', rejected: 'red' }

export default function MyProfilePage() {
  const { me, refresh } = useAuth()
  const [history, setHistory] = useState([])
  const [newName, setNewName] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  const loadHistory = useCallback(async () => {
    const data = await api('/me/name-change-requests')
    setHistory(data.items)
  }, [])

  // Always show fresh data: the admin may have approved a change since login.
  useEffect(() => {
    Promise.all([refresh(), loadHistory()]).catch(setError)
  }, [refresh, loadHistory])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api('/me/name-change-requests', { method: 'POST', body: { requested_name: newName } })
      setNewName('')
      setNotice('Request sent. Your name changes once the admin approves it.')
      await Promise.all([refresh(), loadHistory()])
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const fieldErrors = fieldErrorsOf(error)
  const pending = me.pending_name_change

  return (
    <div className="page">
      <h1 className="page-title">My Profile</h1>

      <div className="grid-2">
        <Card title="Details">
          <dl className="details">
            <dt>My name</dt>
            <dd>{me.display_name}</dd>
            <dt>Role</dt>
            <dd>{me.role || <span className="muted">Not set — ask your admin</span>}</dd>
            <dt>Username</dt>
            <dd className="mono">{me.username}</dd>
          </dl>
          <p className="muted small">Your role is set by the admin.</p>
        </Card>

        <Card title="Change my name">
          {pending ? (
            <Alert tone="info" title="Waiting for admin approval">
              You asked to change your name to “{pending.requested_name}” on {formatDateTime(pending.created_at)}.
            </Alert>
          ) : (
            <form onSubmit={submit} className="stack">
              <Alert tone="success">{notice}</Alert>
              <Alert title={!fieldErrors.requested_name ? error?.title : null}>
                {!fieldErrors.requested_name && error?.message !== error?.title ? error?.message : null}
              </Alert>
              <Field label="New name" error={fieldErrors.requested_name} hint="The admin must approve the change.">
                {(id) => (
                  <input id={id} value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={100} required />
                )}
              </Field>
              <div>
                <Button type="submit" disabled={busy || !newName.trim()}>
                  {busy ? 'Sending…' : 'Request name change'}
                </Button>
              </div>
            </form>
          )}
        </Card>
      </div>

      <ChangePasswordCard />

      <Card title="Name change history">
        {history.length === 0 ? (
          <p className="muted">No requests yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Requested</th>
                <th>New name</th>
                <th>Status</th>
                <th>Reviewed</th>
              </tr>
            </thead>
            <tbody>
              {history.map((r) => (
                <tr key={r.id}>
                  <td className="num">{formatDateTime(r.created_at)}</td>
                  <td>{r.requested_name}</td>
                  <td>
                    <Badge tone={STATUS_TONE[r.status]}>{r.status[0].toUpperCase() + r.status.slice(1)}</Badge>
                  </td>
                  <td className="num">{formatDateTime(r.reviewed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

function ChangePasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const mismatch = confirm !== '' && next !== confirm
  const errors = fieldErrorsOf(error)

  async function submit(event) {
    event.preventDefault()
    if (mismatch) return
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      await api('/me/password', { method: 'PUT', body: { current_password: current, new_password: next } })
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Change my password">
      <form onSubmit={submit} className="password-form">
        {done && <Alert tone="success">Password changed. You were logged out on your other devices.</Alert>}
        {error && !error.fieldErrors.length && (
          <Alert title={error.title}>{error.message !== error.title ? error.message : null}</Alert>
        )}
        <div className="form-grid-3">
          <Field label="Current password">
            {(id) => (
              <input id={id} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            )}
          </Field>
          <Field label="New password" error={errors.new_password} hint="At least 6 characters.">
            {(id) => (
              <input id={id} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
            )}
          </Field>
          <Field label="Repeat new password" error={mismatch ? 'Does not match.' : null}>
            {(id) => (
              <input id={id} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            )}
          </Field>
        </div>
        <div>
          <Button type="submit" disabled={busy || mismatch || !current || !next}>
            {busy ? 'Saving…' : 'Change password'}
          </Button>
        </div>
      </form>
    </Card>
  )
}
