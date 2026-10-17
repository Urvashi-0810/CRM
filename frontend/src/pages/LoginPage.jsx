import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Alert, Button, Field } from '../components/ui'

export default function LoginPage() {
  const { me, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (me) return <Navigate to={location.state?.from || '/demands'} replace />

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate(location.state?.from || '/demands', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand brand-center">
          <span className="brand-mark" aria-hidden="true">SG</span>
          <span>
            <strong>Shield Global</strong>
            <small>Demand Letter CRM</small>
          </span>
        </div>
        <h1>Sign in</h1>
        <Alert title={error?.title}>{error?.message !== error?.title ? error?.message : null}</Alert>
        <Field label="Username">
          {(id) => (
            <input
              id={id}
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          )}
        </Field>
        <Field label="Password">
          {(id) => (
            <input
              id={id}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          )}
        </Field>
        <Button type="submit" disabled={busy} className="btn-block">
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
        <p className="muted small">Accounts are created by your admin.</p>
      </form>
    </div>
  )
}
