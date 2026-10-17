import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Alert, Button, Card, Field, formatDateTime } from '../components/ui'

const AdminContext = createContext(null)

// Admin pages call this with any API error: if the admin unlock expired,
// the gate shows the password prompt again instead of a raw error.
export function useAdmin() {
  return useContext(AdminContext)
}

export default function AdminGate() {
  const { refresh } = useAuth()
  const [status, setStatus] = useState(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setStatus(await api('/admin/session'))
  }, [])

  useEffect(() => {
    load().catch(setError)
  }, [load])

  const handleError = useCallback(
    (err) => {
      if (err?.is?.('admin-session-required')) {
        setStatus((s) => ({ ...s, active: false, expires_at: null }))
        return true
      }
      return false
    },
    [],
  )

  async function unlock(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api('/admin/session', { method: 'POST', body: { admin_password: password } })
      setPassword('')
      await Promise.all([load(), refresh()])
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function lock() {
    await api('/admin/session', { method: 'DELETE' })
    await Promise.all([load(), refresh()])
  }

  if (!status) {
    return <div className="page">{error ? <Alert title={error.title}>{error.message}</Alert> : <p className="muted">Loading…</p>}</div>
  }

  if (!status.active) {
    return (
      <div className="page">
        <h1 className="page-title">Admin</h1>
        <div className="narrow">
          <Card title="Enter the admin password">
            {!status.password_configured ? (
              <Alert title="The admin password has not been set up yet.">
                Run the bootstrap script on the server (see README).
              </Alert>
            ) : (
              <form onSubmit={unlock} className="stack">
                <p className="muted small">The admin page needs a separate password, in addition to your login.</p>
                <Alert title={error?.title}>{error?.message !== error?.title ? error?.message : null}</Alert>
                <Field label="Admin password">
                  {(id) => (
                    <input
                      id={id}
                      type="password"
                      autoComplete="off"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      autoFocus
                    />
                  )}
                </Field>
                <div>
                  <Button type="submit" disabled={busy || !password}>
                    {busy ? 'Checking…' : 'Open admin page'}
                  </Button>
                </div>
              </form>
            )}
          </Card>
        </div>
      </div>
    )
  }

  return (
    <AdminContext.Provider value={{ handleError }}>
      <div className="page">
        <div className="page-header">
          <h1 className="page-title">Admin</h1>
          <div className="page-actions">
            <span className="muted small">Unlocked until {formatDateTime(status.expires_at)}</span>
            <Button variant="ghost" size="sm" onClick={lock}>
              Lock admin
            </Button>
          </div>
        </div>
        <nav className="tabs" aria-label="Admin sections">
          <NavLink to="/admin/users" className="tab">
            Users
          </NavLink>
          <NavLink to="/admin/name-requests" className="tab">
            Name-change requests
          </NavLink>
          <NavLink to="/admin/ai" className="tab">
            AI settings
          </NavLink>
          <NavLink to="/admin/usage" className="tab">
            Usage &amp; budget
          </NavLink>
          <NavLink to="/admin/password" className="tab">
            Admin password
          </NavLink>
        </nav>
        <Outlet />
      </div>
    </AdminContext.Provider>
  )
}
