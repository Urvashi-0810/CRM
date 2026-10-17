import { useState } from 'react'
import { api } from '../api/client'
import { Alert, Button, Card, Field, fieldErrorsOf } from '../components/ui'
import { useAdmin } from './AdminGate'

export default function AdminPasswordPage() {
  const { handleError } = useAdmin()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const mismatch = confirm && next !== confirm
  const errors = fieldErrorsOf(error)

  async function submit(event) {
    event.preventDefault()
    if (mismatch) return
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      await api('/admin/password', { method: 'PUT', body: { current_password: current, new_password: next } })
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <Card title="Change the admin password">
        <form onSubmit={submit} className="stack">
          {done && <Alert tone="success">Admin password changed. Tell the other admins.</Alert>}
          {error && !error.fieldErrors.length && <Alert title={error.title}>{error.message !== error.title ? error.message : null}</Alert>}
          <Field label="Current admin password">
            {(id) => <input id={id} type="password" autoComplete="off" value={current} onChange={(e) => setCurrent(e.target.value)} required />}
          </Field>
          <Field label="New admin password" error={errors.new_password}>
            {(id) => <input id={id} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />}
          </Field>
          <Field label="Repeat new admin password" error={mismatch ? 'Does not match.' : null}>
            {(id) => <input id={id} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />}
          </Field>
          <div>
            <Button type="submit" disabled={busy || mismatch}>
              {busy ? 'Saving…' : 'Change admin password'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
