import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Alert, Badge, Button, Card, ErrorAlert, Field, fieldErrorsOf, formatDateTime } from '../components/ui'
import { useAdmin } from './AdminGate'

const PROVIDER_LABEL = { claude: 'Claude (Anthropic)', gemini: 'Gemini (Google)', test: 'Test — no AI (development only)' }

function ProvidersCard() {
  const { handleError } = useAdmin()
  const [data, setData] = useState(null)
  const [form, setForm] = useState({ provider: 'claude', model: '', api_key: '' })
  const [keyFor, setKeyFor] = useState(null) // config id whose key is being replaced
  const [newKey, setNewKey] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const d = await api('/admin/llm-providers')
      setData(d)
      setForm((f) => ({ ...f, model: f.model || d.model_suggestions[f.provider]?.[0] || '' }))
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [handleError])

  useEffect(() => {
    load()
  }, [load])

  async function run(fn) {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <Card title="AI provider">{error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>}</Card>
  const errors = fieldErrorsOf(error)

  return (
    <Card title="AI provider">
      <p className="muted small">
        The active provider writes every letter. API keys are stored encrypted and are never shown again — only their last
        4 characters.
      </p>
      {error && !error.fieldErrors.length && <ErrorAlert error={error} />}
      {data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Model</th>
              <th>API key</th>
              <th>Status</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.id}>
                <td>{PROVIDER_LABEL[c.provider] || c.provider}</td>
                <td className="mono">{c.model}</td>
                <td className="mono">{c.has_key ? `••••${c.key_last4}` : '—'}</td>
                <td>{c.is_active ? <Badge tone="green">Active</Badge> : <Badge>Inactive</Badge>}</td>
                <td className="row-actions">
                  {!c.is_active && (
                    <Button size="sm" disabled={busy} onClick={() => run(() => api(`/admin/llm-providers/${c.id}/activate`, { method: 'POST' }))}>
                      Make active
                    </Button>
                  )}
                  {c.provider !== 'test' && (
                    <Button variant="ghost" size="sm" onClick={() => setKeyFor(keyFor === c.id ? null : c.id)}>
                      Replace key
                    </Button>
                  )}
                  {!c.is_active && (
                    <Button variant="danger" size="sm" disabled={busy} onClick={() => run(() => api(`/admin/llm-providers/${c.id}`, { method: 'DELETE' }))}>
                      Remove
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {keyFor && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            run(async () => {
              await api(`/admin/llm-providers/${keyFor}`, { method: 'PATCH', body: { api_key: newKey } })
              setKeyFor(null)
              setNewKey('')
            })
          }}
        >
          <Field label="New API key">
            {(id) => <input id={id} type="password" autoComplete="off" value={newKey} onChange={(e) => setNewKey(e.target.value)} required />}
          </Field>
          <Button type="submit" disabled={busy || newKey.length < 8}>
            Save key
          </Button>
        </form>
      )}

      <form
        className="provider-form"
        onSubmit={(e) => {
          e.preventDefault()
          run(async () => {
            const body = { provider: form.provider, model: form.model }
            if (form.api_key) body.api_key = form.api_key
            await api('/admin/llm-providers', { method: 'POST', body })
            setForm({ ...form, api_key: '' })
          })
        }}
      >
        <h3>Add a provider</h3>
        <div className="form-grid-3">
          <Field label="Provider">
            {(id) => (
              <select
                id={id}
                value={form.provider}
                onChange={(e) => setForm({ provider: e.target.value, model: data.model_suggestions[e.target.value]?.[0] || '', api_key: '' })}
              >
                {data.providers.map((p) => (
                  <option key={p} value={p}>
                    {PROVIDER_LABEL[p]}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Model" error={errors.model} hint="Pick a suggestion or type any model name the provider offers.">
            {(id) => (
              <>
                <input id={id} list="model-suggestions" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} required />
                <datalist id="model-suggestions">
                  {(data.model_suggestions[form.provider] || []).map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </>
            )}
          </Field>
          {form.provider !== 'test' && (
            <Field label="API key" error={errors.api_key}>
              {(id) => (
                <input id={id} type="password" autoComplete="off" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} required />
              )}
            </Field>
          )}
        </div>
        <div>
          <Button type="submit" disabled={busy}>
            Add provider
          </Button>
        </div>
      </form>
    </Card>
  )
}

function PromptCard() {
  const { handleError } = useAdmin()
  const [items, setItems] = useState([])
  const [body, setBody] = useState('')
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api('/admin/prompts')
      setItems(data.items)
      setBody(data.items.find((p) => p.is_active)?.body || '')
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [handleError])

  useEffect(() => {
    load()
  }, [load])

  const active = items.find((p) => p.is_active)

  async function save() {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await api('/admin/prompts', { method: 'POST', body: { body } })
      setSaved(true)
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function activate(id) {
    try {
      await api(`/admin/prompts/${id}/activate`, { method: 'POST' })
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }

  return (
    <Card title="Base prompt">
      <p className="muted small">
        The client’s instructions for every letter: what it should contain and how it should read. The app’s own rules
        (never invent details, ask about missing information, refuse unrelated requests) always apply on top.
      </p>
      {saved && <Alert tone="success">Saved. New messages use this prompt.</Alert>}
      {error && <ErrorAlert error={error} />}
      <textarea className="prompt-editor" value={body} onChange={(e) => setBody(e.target.value)} rows={12} aria-label="Base prompt" />
      <div className="row-gap">
        <Button onClick={save} disabled={busy || body.trim().length < 20 || body === active?.body}>
          {busy ? 'Saving…' : 'Save as new version'}
        </Button>
      </div>
      {items.length > 1 && (
        <details>
          <summary className="small">Earlier versions ({items.length - 1})</summary>
          <ul className="version-list">
            {items
              .filter((p) => !p.is_active)
              .map((p) => (
                <li key={p.id}>
                  <span className="small">{formatDateTime(p.created_at)}</span>
                  <span className="muted small clip">{p.body.slice(0, 120)}</span>
                  <Button variant="ghost" size="sm" onClick={() => activate(p.id)}>
                    Use this
                  </Button>
                </li>
              ))}
          </ul>
        </details>
      )}
    </Card>
  )
}

function LetterheadCard() {
  const { handleError } = useAdmin()
  const [items, setItems] = useState([])
  const [header, setHeader] = useState(null)
  const [footer, setFooter] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await api('/admin/letterheads')).items)
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [handleError])

  useEffect(() => {
    load()
  }, [load])

  const active = items.find((l) => l.is_active)

  async function upload(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('header', header)
    form.append('footer', footer)
    try {
      await api('/admin/letterheads', { method: 'POST', form })
      setHeader(null)
      setFooter(null)
      event.target.reset()
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Letterhead">
      <p className="muted small">
        Header and footer images (PNG or JPG) placed across the full page width of every letter. Use images without the
        “Demand Order ID” and “Date” text — the app writes those. Letters already generated keep the letterhead they were
        made with.
      </p>
      {error && <ErrorAlert error={error} />}
      {active ? (
        <div className="letterhead-preview">
          <img src={`/api/v1/files/${active.header_file_id}`} alt="Current header" />
          <div className="letterhead-gap muted small">letter content</div>
          <img src={`/api/v1/files/${active.footer_file_id}`} alt="Current footer" />
        </div>
      ) : (
        <Alert tone="info">No letterhead yet. Letters are generated without header and footer until you upload one.</Alert>
      )}
      <form className="inline-form" onSubmit={upload}>
        <Field label="Header image">
          {(id) => <input id={id} type="file" accept="image/png,image/jpeg" onChange={(e) => setHeader(e.target.files[0] || null)} required />}
        </Field>
        <Field label="Footer image">
          {(id) => <input id={id} type="file" accept="image/png,image/jpeg" onChange={(e) => setFooter(e.target.files[0] || null)} required />}
        </Field>
        <Button type="submit" disabled={busy || !header || !footer}>
          {busy ? 'Uploading…' : active ? 'Replace letterhead' : 'Upload letterhead'}
        </Button>
      </form>
    </Card>
  )
}

function ReferenceLettersCard() {
  const { handleError } = useAdmin()
  const [items, setItems] = useState([])
  const [file, setFile] = useState(null)
  const [label, setLabel] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setItems((await api('/admin/reference-letters')).items)
    } catch (err) {
      if (!handleError(err)) setError(err)
    }
  }, [handleError])

  useEffect(() => {
    load()
  }, [load])

  async function run(fn) {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await load()
    } catch (err) {
      if (!handleError(err)) setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Reference letters">
      <p className="muted small">
        Example demand letters whose <strong>format</strong> the AI follows (never their data). Active ones are used for
        every letter, unless the user attaches their own reference letter in the chat — then only theirs is used.
      </p>
      {error && <ErrorAlert error={error} />}
      {items.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>File</th>
              <th>Status</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id}>
                <td>{r.label}</td>
                <td>
                  <a href={`/api/v1/files/${r.file_id}`}>{r.filename}</a>
                </td>
                <td>{r.is_active ? <Badge tone="green">Used</Badge> : <Badge>Not used</Badge>}</td>
                <td className="row-actions">
                  <Button variant="ghost" size="sm" disabled={busy}
                    onClick={() => run(() => api(`/admin/reference-letters/${r.id}`, { method: 'PATCH', body: { is_active: !r.is_active } }))}>
                    {r.is_active ? 'Stop using' : 'Use'}
                  </Button>
                  <Button variant="danger" size="sm" disabled={busy}
                    onClick={() => run(() => api(`/admin/reference-letters/${r.id}`, { method: 'DELETE' }))}>
                    Remove
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No reference letters yet — the AI follows the base prompt only.</p>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          const form = new FormData()
          form.append('file', file)
          form.append('label', label)
          run(async () => {
            await api('/admin/reference-letters', { method: 'POST', form })
            setFile(null)
            setLabel('')
            e.target.reset()
          })
        }}
      >
        <Field label="Reference letter (.docx, .pdf, .txt)">
          {(id) => <input id={id} type="file" accept=".docx,.pdf,.txt" onChange={(e) => setFile(e.target.files[0] || null)} required />}
        </Field>
        <Field label="Name (optional)">
          {(id) => <input id={id} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={200} placeholder="e.g. Qatar FM format" />}
        </Field>
        <Button type="submit" disabled={busy || !file}>
          Add reference letter
        </Button>
      </form>
    </Card>
  )
}

export default function AdminAiPage() {
  return (
    <div className="stack">
      <ProvidersCard />
      <PromptCard />
      <ReferenceLettersCard />
      <LetterheadCard />
    </div>
  )
}
