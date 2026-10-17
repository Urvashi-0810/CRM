import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { DownloadIcon, EditIcon } from './icons'
import { Alert, Badge, Button, ErrorAlert, Modal, formatDateTime } from './ui'

const SOURCE_LABEL = {
  generated: 'Generated',
  prompt_edit: 'Prompt edit',
  uploaded_edit: 'Uploaded from Word',
  approval_stamp: 'Approval stamp',
  restored: 'Restored',
}

export function ApproveDialog({ demand, letter, onClose, onApproved }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const missing = letter.missing_fields || []

  async function approve() {
    setBusy(true)
    setError(null)
    try {
      await api(`/demands/${demand.id}/approve`, { method: 'POST', body: { version_no: letter.version_no } })
      onApproved()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Approve ${demand.demand_code}?`} onClose={onClose}>
      <div className="stack">
        <p>
          You are approving <strong>version {letter.version_no}</strong>. The approval date is written into the letter, the
          DRAFT mark is removed, and the letter moves to the demand list. You can still edit it afterwards.
        </p>
        {missing.length > 0 && (
          <Alert tone="error" title={`${missing.length} field${missing.length === 1 ? '' : 's'} still to be filled:`}>
            <span>{missing.join(', ')}. They stay highlighted in the letter if you approve now.</span>
          </Alert>
        )}
        <ErrorAlert error={error} />
        <div className="row-end">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={approve} disabled={busy}>
            {busy ? 'Approving…' : missing.length ? 'Approve anyway' : 'Approve'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function EditMenu({ demand, letter, onFocusChat, onUploaded, disabled }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const input = useRef(null)
  const box = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  async function upload(file) {
    if (!file) return
    setBusy(true)
    setError(null)
    setDone(null)
    if (file.size > 10_000_000) {
      setError({ title: 'File too large', message: `"${file.name}" is larger than 10 MB. Compress large pictures in Word and save again.` })
      setBusy(false)
      return
    }
    const form = new FormData()
    form.append('file', file)
    try {
      const result = await api(`/demands/${demand.id}/edited-uploads`, { method: 'POST', form })
      setDone(result)
      onUploaded()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="menu-wrap" ref={box}>
      <Button variant="ghost" size="sm" onClick={() => setOpen(!open)} disabled={disabled} aria-expanded={open}>
        <EditIcon /> Edit
      </Button>
      {open && (
        <div className="menu" role="menu">
          <button
            role="menuitem"
            className="menu-item"
            onClick={() => {
              setOpen(false)
              onFocusChat()
            }}
          >
            <strong>Describe the change in the chat</strong>
            <span className="muted small">The AI updates the newest version.</span>
          </button>
          <div className="menu-item menu-item-static">
            <strong>Edit in Word, then upload</strong>
            <span className="muted small">1. Download, edit and save the .docx. 2. Upload it here — it becomes the newest version exactly as you saved it.</span>
            <div className="row-gap">
              <a className="btn btn-ghost btn-sm" href={`/api/v1/demands/${demand.id}/docx`}>
                <DownloadIcon /> Download v{letter.version_no}
              </a>
              <Button size="sm" onClick={() => input.current?.click()} disabled={busy}>
                {busy ? 'Uploading…' : 'Upload edited letter'}
              </Button>
              <input
                ref={input}
                type="file"
                accept=".docx"
                hidden
                onChange={(e) => {
                  upload(e.target.files[0])
                  e.target.value = ''
                }}
              />
            </div>
            <ErrorAlert error={error} />
            {done && (
              <Alert tone="success">
                Saved as version {done.version_no}.{!done.header_found && ' (No letterhead header found in the file.)'}
              </Alert>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export function VersionsPanel({ demand, current, viewing, onView, onRestored, disabled }) {
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    api(`/demands/${demand.id}/versions`).then((d) => setItems(d.items)).catch(setError)
  }, [demand.id, current])

  async function restore(no) {
    setBusy(no)
    setError(null)
    try {
      await api(`/demands/${demand.id}/versions/${no}/restore`, { method: 'POST' })
      onRestored()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="versions">
      <ErrorAlert error={error} />
      <ul>
        {items.map((v) => (
          <li key={v.version_no} className={viewing === v.version_no ? 'active' : ''}>
            <button className="version-main" onClick={() => onView(v.version_no)}>
              <strong>v{v.version_no}</strong>
              <span>
                {SOURCE_LABEL[v.source] || v.source}
                {v.restored_from_no ? ` of v${v.restored_from_no}` : ''}
              </span>
              <span className="muted small">
                {formatDateTime(v.created_at)} · {v.created_by}
              </span>
              {v.version_no === current && <Badge tone="green">Newest</Badge>}
              {v.missing_count > 0 && <Badge tone="amber">{v.missing_count} to fill</Badge>}
            </button>
            <div className="version-actions">
              <a className="icon-action" href={`/api/v1/demands/${demand.id}/versions/${v.version_no}/docx`} aria-label={`Download version ${v.version_no}`} title="Download">
                <DownloadIcon />
              </a>
              {v.version_no !== current && (
                <Button variant="ghost" size="sm" disabled={disabled || busy !== null} onClick={() => restore(v.version_no)}>
                  {busy === v.version_no ? 'Restoring…' : 'Restore'}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
