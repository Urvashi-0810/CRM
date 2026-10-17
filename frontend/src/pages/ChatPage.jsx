import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { ApproveDialog, EditMenu, VersionsPanel } from '../components/LetterActions'
import LetterPreview from '../components/LetterPreview'
import { DownloadIcon } from '../components/icons'
import { Alert, Badge, Button, ConfirmModal, ErrorAlert, formatDateTime } from '../components/ui'

const KIND_OPTIONS = [
  { value: 'inquiry', label: 'Inquiry' },
  { value: 'jd', label: 'JD' },
  { value: 'custom_reference', label: 'Reference letter' },
]
const KIND_LABEL = Object.fromEntries(KIND_OPTIONS.map((k) => [k.value, k.label]))
const MAX_FILE_MB = 10
const POLL_MS = 2000
const PASTED_INQUIRY_NAME = 'Demand inquiry (pasted mail).docx'
const ACCEPT_ANY = '.docx,.xlsx,.xlsm,.csv,.txt,.pdf,.png,.jpg,.jpeg,.webp,.gif'
const ACCEPT_INQUIRY = '.docx,.pdf,.txt'

function guessKind(name, hasInquiry) {
  const ext = name.split('.').pop().toLowerCase()
  if (!hasInquiry && ext === 'docx') return 'inquiry'
  return 'jd'
}

function sizeLabel(bytes) {
  return bytes > 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`
}

function Message({ m }) {
  const mine = m.sender === 'user'
  if (m.kind === 'event') {
    return (
      <div className="msg-event" role="note">
        {m.body} <span className="muted small">· {formatDateTime(m.created_at)}</span>
      </div>
    )
  }
  return (
    <div className={`msg ${mine ? 'msg-user' : 'msg-ai'} ${m.kind === 'error' ? 'msg-error' : ''}`}>
      <div className="msg-meta">
        {mine ? m.author || 'You' : 'Assistant'} · {formatDateTime(m.created_at)}
      </div>
      {m.files?.length > 0 && (
        <ul className="msg-files">
          {m.files.map((f) => (
            <li key={f.id}>
              <a href={`/api/v1/files/${f.id}`} target="_blank" rel="noreferrer">
                📎 {f.name}
              </a>
              <span className="file-kind">{KIND_LABEL[f.kind]}</span>
              <span className="muted small">{sizeLabel(f.size_bytes)}</span>
            </li>
          ))}
        </ul>
      )}
      {m.body && <div className="msg-body">{m.body}</div>}
      {m.kind === 'questions' && m.data?.questions?.length > 0 && (
        <ol className="msg-questions">
          {m.data.questions.map((q, i) => (
            <li key={i}>{q}</li>
          ))}
        </ol>
      )}
      {m.kind === 'letter' && (
        <div className="msg-letter">
          <Badge tone="green">Letter version {m.data?.version_no} ready</Badge>
          {m.data?.missing_fields?.length > 0 && (
            <span className="small">Still to fill: {m.data.missing_fields.join(', ')}</span>
          )}
        </div>
      )}
    </div>
  )
}

function InquiryMenu({ onPaste, onUpload, disabled, small, up }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  function pick(action) {
    setOpen(false)
    action()
  }

  return (
    <div className="menu-wrap" ref={box}>
      <Button
        type="button"
        size={small ? 'sm' : undefined}
        variant={small ? 'ghost' : 'primary'}
        className={small ? 'quick-attach-btn' : ''}
        onClick={() => setOpen(!open)}
        disabled={disabled}
        aria-expanded={open}
      >
        + Add Demand Inquiry ▾
      </Button>
      {open && (
        <div className={`menu attach-menu ${up ? 'menu-up' : ''}`} role="menu">
          <button type="button" role="menuitem" className="menu-item" onClick={() => pick(onPaste)}>
            <strong>Paste the mail text</strong>
            <span className="muted small">Saved as a .docx for you</span>
          </button>
          <button type="button" role="menuitem" className="menu-item" onClick={() => pick(onUpload)}>
            <strong>Upload a file</strong>
            <span className="muted small">.docx, .pdf or .txt</span>
          </button>
        </div>
      )}
    </div>
  )
}

function PasteInquiryCard({ value, onChange, onAttach, onUpload, onClose, textareaRef, disabled }) {
  return (
    <div className="paste-card">
      <div className="paste-card-head">
        <strong>📄 Paste Demand Inquiry / Mail</strong>
        <span className="paste-badge">Auto-converts to .docx</span>
        {onClose && (
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            ×
          </button>
        )}
      </div>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            onAttach()
          }
        }}
        rows={5}
        placeholder="Paste the mail body (or inquiry text) here. It is saved as a .docx and attached as the demand inquiry."
        aria-label="Pasted demand inquiry"
        disabled={disabled}
      />
      <div className="paste-card-foot">
        <span className="muted small">
          Or{' '}
          <button type="button" className="link-btn" onClick={onUpload} disabled={disabled}>
            upload a .docx / .pdf / .txt
          </button>
        </span>
        <Button type="button" size="sm" onClick={onAttach} disabled={disabled || !value.trim()}>
          Attach as Demand Inquiry (.docx)
        </Button>
      </div>
    </div>
  )
}

export default function ChatPage() {
  const { demandId } = useParams()
  const navigate = useNavigate()
  const [demand, setDemand] = useState(null)
  const [messages, setMessages] = useState([])
  const [letter, setLetter] = useState(null)
  const [aiStatus, setAiStatus] = useState(null)
  const [job, setJob] = useState(null)
  const [text, setText] = useState('')
  const [files, setFiles] = useState([]) // {file, kind}
  const [pastedInquiry, setPastedInquiry] = useState(null) // attached mail text, sent as inquiry_text
  const [pasteDraft, setPasteDraft] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [error, setError] = useState(null)
  const [sending, setSending] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [approving, setApproving] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [viewing, setViewing] = useState(null) // an older version being looked at
  const fileInput = useRef(null)
  const pickKind = useRef(null) // kind chosen by an "Add JD / Add Demand Inquiry" button
  const pasteBox = useRef(null)
  const composer = useRef(null)
  const listEnd = useRef(null)

  const loadMessages = useCallback(async () => {
    setMessages((await api(`/demands/${demandId}/messages`)).items)
  }, [demandId])

  const loadLetter = useCallback(async () => {
    try {
      setLetter(await api(`/demands/${demandId}/letter`))
    } catch (err) {
      if (err.status === 404 && err.is('no-letter-yet')) setLetter(null)
      else throw err
    }
  }, [demandId])

  const loadDemand = useCallback(async () => setDemand(await api(`/demands/${demandId}`)), [demandId])

  useEffect(() => {
    Promise.all([
      loadDemand(),
      loadMessages(),
      loadLetter(),
      api('/ai/status').then(setAiStatus),
      api(`/demands/${demandId}/active-job`).then(setJob),
    ]).catch(setError)
  }, [demandId, loadDemand, loadMessages, loadLetter])

  // While a reply is being prepared, check every 2 s. Closing the page is fine:
  // the server keeps working and the reply is here when you come back.
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.state)) return undefined
    const timer = setInterval(async () => {
      try {
        const latest = await api(`/jobs/${job.id}`)
        if (!['queued', 'running'].includes(latest.state)) {
          setJob(null)
          await Promise.all([loadMessages(), loadLetter(), loadDemand()])
        }
      } catch (err) {
        setError(err)
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [job, loadMessages, loadLetter, loadDemand])

  useEffect(() => {
    listEnd.current?.scrollIntoView({ block: 'end' })
  }, [messages, job])

  const hasInquiry = messages.some((m) => m.files?.some((f) => f.kind === 'inquiry'))

  function pickFiles(kind) {
    pickKind.current = kind
    fileInput.current.accept = kind === 'inquiry' ? ACCEPT_INQUIRY : ACCEPT_ANY
    fileInput.current.click()
  }

  function openPaste() {
    setPasteOpen(true)
    setTimeout(() => pasteBox.current?.focus())
  }

  function attachPasted() {
    if (!pasteDraft.trim()) return
    setPastedInquiry(pasteDraft.trim())
    setPasteDraft('')
    setPasteOpen(false)
    composer.current?.focus()
  }

  function addFiles(list, forcedKind = null) {
    setError(null)
    const added = []
    let inquiryTaken = hasInquiry || Boolean(pastedInquiry) || files.some((f) => f.kind === 'inquiry')
    for (const file of list) {
      if (file.size > MAX_FILE_MB * 1_000_000) {
        setError({
          title: 'File too large',
          message: `"${file.name}" is larger than ${MAX_FILE_MB} MB. Upload a smaller file (for example, only the pages or sheets you need).`,
          fieldErrors: [],
        })
        continue
      }
      const kind = forcedKind || guessKind(file.name, inquiryTaken)
      if (kind === 'inquiry') inquiryTaken = true
      added.push({ file, kind })
    }
    setFiles((current) => [...current, ...added].slice(0, 10))
  }

  async function send(event) {
    event?.preventDefault()
    if (sending || busy || !canSend) return
    setSending(true)
    setError(null)
    const form = new FormData()
    form.append('text', text)
    if (pastedInquiry) form.append('inquiry_text', pastedInquiry)
    for (const f of files) {
      form.append('files', f.file)
      form.append('kinds', f.kind)
    }
    try {
      const result = await api(`/demands/${demandId}/messages`, { method: 'POST', form })
      setMessages((current) => [...current, result.message])
      setJob(result.job)
      setText('')
      setFiles([])
      setPastedInquiry(null)
    } catch (err) {
      setError(err)
    } finally {
      setSending(false)
    }
  }

  async function deleteDraft() {
    setDeleting(true)
    try {
      await api(`/demands/${demandId}`, { method: 'DELETE' })
      navigate('/demands', { replace: true })
    } catch (err) {
      setError(err)
      setConfirmDelete(false)
    } finally {
      setDeleting(false)
    }
  }

  const busy = Boolean(job && ['queued', 'running'].includes(job.state))
  const canSend = Boolean(text.trim() || files.length > 0 || pastedInquiry)

  async function viewVersion(no) {
    if (!letter || no === letter.version_no) {
      setViewing(null)
      return
    }
    try {
      setViewing(await api(`/demands/${demandId}/versions/${no}`))
    } catch (err) {
      setError(err)
    }
  }

  async function refreshAll() {
    setViewing(null)
    await Promise.all([loadMessages(), loadLetter(), loadDemand()])
  }

  const shown = viewing || letter

  if (!demand) {
    return <div className="page">{error ? <ErrorAlert error={error} /> : <p className="muted">Loading…</p>}</div>
  }

  return (
    <div className="chat-page">
      <header className="chat-header">
        <div className="chat-title">
          <Link to="/demands" className="back-link">
            ← Demand list
          </Link>
          <h1>{demand.demand_code}</h1>
          <Badge tone={demand.lifecycle === 'approved' ? 'green' : 'amber'}>
            {demand.lifecycle === 'approved' ? 'Approved' : 'Yet to be approved'}
          </Badge>
          {demand.employer && <span className="muted small">{demand.employer}</span>}
        </div>
        <div className="row-gap">
          {letter && (
            <a className="btn btn-ghost btn-sm" href={`/api/v1/demands/${demandId}/docx`}>
              <DownloadIcon /> Download .docx (v{letter.version_no})
            </a>
          )}
          {demand.lifecycle === 'draft' && (
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)} disabled={busy}>
              Delete draft
            </Button>
          )}
        </div>
      </header>

      <div className="chat-layout">
        <section className="chat-panel" aria-label="Chat">
          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty">
                <h2>Start the letter</h2>
                <p>
                  Add the <strong>demand inquiry</strong> (paste the mail, or upload a file) and the <strong>JD</strong>{' '}
                  if you have one, then press Enter.
                </p>
                <p className="muted small">
                  Optional: attach a reference letter to copy its format, or type extra instructions. The assistant
                  asks about anything missing before writing, and never invents details.
                </p>
                <div className="start-actions">
                  <Button type="button" variant="ghost" onClick={() => pickFiles('jd')} disabled={busy}>
                    + Add JD
                  </Button>
                  <InquiryMenu
                    onPaste={() => pasteBox.current?.focus()}
                    onUpload={() => pickFiles('inquiry')}
                    disabled={busy}
                  />
                </div>
                {!pastedInquiry && (
                  <PasteInquiryCard
                    value={pasteDraft}
                    onChange={setPasteDraft}
                    onAttach={attachPasted}
                    onUpload={() => pickFiles('inquiry')}
                    textareaRef={pasteBox}
                    disabled={busy}
                  />
                )}
              </div>
            )}
            {messages.map((m) => (
              <Message key={m.id} m={m} />
            ))}
            {busy && (
              <div className="msg msg-ai generating" role="status">
                <span className="dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                Generating… you can leave this page; the reply will be saved here.
              </div>
            )}
            <div ref={listEnd} />
          </div>

          {aiStatus && !aiStatus.configured && (
            <Alert tone="info" title="The AI is not set up yet.">
              Ask the admin to choose a provider and enter its API key (Admin → AI settings).
            </Alert>
          )}
          {aiStatus?.configured && !aiStatus.letterhead && (
            <Alert tone="info">No letterhead uploaded yet — letters will be generated without header and footer.</Alert>
          )}
          <ErrorAlert error={error} />

          {pasteOpen && messages.length > 0 && (
            <div className="paste-card-dock">
              <PasteInquiryCard
                value={pasteDraft}
                onChange={setPasteDraft}
                onAttach={attachPasted}
                onUpload={() => pickFiles('inquiry')}
                onClose={() => setPasteOpen(false)}
                textareaRef={pasteBox}
                disabled={busy}
              />
            </div>
          )}

          <form
            className={`composer ${busy ? 'composer-busy' : ''}`}
            onSubmit={send}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              addFiles([...e.dataTransfer.files])
            }}
          >
            {(files.length > 0 || pastedInquiry) && (
              <ul className="pending-files">
                {pastedInquiry && (
                  <li>
                    <span className="pending-name" title={PASTED_INQUIRY_NAME}>
                      📝 {PASTED_INQUIRY_NAME}
                    </span>
                    <span className="muted small">{pastedInquiry.length.toLocaleString()} characters</span>
                    <span className="file-kind">Inquiry</span>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => {
                        setPasteDraft(pastedInquiry)
                        setPastedInquiry(null)
                        openPaste()
                      }}
                    >
                      Edit
                    </button>
                    <button type="button" className="icon-btn" aria-label="Remove pasted inquiry" onClick={() => setPastedInquiry(null)}>
                      ×
                    </button>
                  </li>
                )}
                {files.map((f, i) => (
                  <li key={i}>
                    <span className="pending-name" title={f.file.name}>
                      📎 {f.file.name}
                    </span>
                    <span className="muted small">{sizeLabel(f.file.size)}</span>
                    <select
                      aria-label={`What is ${f.file.name}?`}
                      value={f.kind}
                      onChange={(e) => setFiles(files.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}
                    >
                      {KIND_OPTIONS.map((k) => (
                        <option key={k.value} value={k.value}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                    <button type="button" className="icon-btn" aria-label={`Remove ${f.file.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="composer-row">
              <button type="button" className="icon-btn attach-btn" onClick={() => pickFiles(null)} aria-label="Attach files" title="Attach files">
                📎
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                hidden
                accept={ACCEPT_ANY}
                onChange={(e) => {
                  addFiles([...e.target.files], pickKind.current)
                  e.target.value = ''
                }}
              />
              <textarea
                ref={composer}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) send(e)
                }}
                placeholder={
                  busy
                    ? 'Waiting for the reply…'
                    : letter
                      ? 'Ask for a change (e.g. "make the salary column bold") or ask a question…'
                      : 'Type instructions or answers… (Enter to send, Shift+Enter for a new line)'
                }
                rows={2}
                aria-label="Message"
                disabled={busy}
              />
              <Button type="submit" disabled={sending || busy || !canSend}>
                {sending ? 'Sending…' : 'Send'}
              </Button>
            </div>
            <div className="quick-attach">
              <span className="muted small">Quick attach:</span>
              <Button type="button" variant="ghost" size="sm" className="quick-attach-btn" onClick={() => pickFiles('jd')} disabled={busy}>
                + Add JD
              </Button>
              <InquiryMenu
                small
                up
                onPaste={() => (messages.length === 0 ? pasteBox.current?.focus() : openPaste())}
                onUpload={() => pickFiles('inquiry')}
                disabled={busy}
              />
            </div>
          </form>
        </section>

        <section className="preview-panel" aria-label="Letter preview">
          {letter ? (
            <>
              <div className="letter-bar">
                <div className="row-gap">
                  {demand.lifecycle === 'draft' && (
                    <Button size="sm" onClick={() => setApproving(true)} disabled={busy || Boolean(viewing)}>
                      ✓ Approve
                    </Button>
                  )}
                  <EditMenu
                    demand={demand}
                    letter={letter}
                    disabled={busy}
                    onFocusChat={() => composer.current?.focus()}
                    onUploaded={refreshAll}
                  />
                  <Button variant="ghost" size="sm" onClick={() => setShowVersions(!showVersions)} aria-expanded={showVersions}>
                    Versions ({letter.version_no})
                  </Button>
                </div>
                {letter.missing_fields?.length > 0 && !viewing && (
                  <Badge tone="amber">{letter.missing_fields.length} to fill</Badge>
                )}
              </div>
              {showVersions && (
                <VersionsPanel
                  demand={demand}
                  current={letter.version_no}
                  viewing={viewing?.version_no || letter.version_no}
                  onView={viewVersion}
                  onRestored={refreshAll}
                  disabled={busy}
                />
              )}
              {viewing && (
                <Alert tone="info" title={`Viewing version ${viewing.version_no} — not the newest (v${letter.version_no}).`}>
                  <span>
                    <button className="link-btn" onClick={() => setViewing(null)}>
                      Back to the newest
                    </button>{' '}
                    or restore it from the Versions list.
                  </span>
                </Alert>
              )}
              <div className="preview-head">
                <span>
                  Version {shown.version_no} · {formatDateTime(shown.created_at)}
                </span>
              </div>
              <LetterPreview letter={shown} />
            </>
          ) : (
            <div className="preview-empty">The letter preview appears here once it is generated.</div>
          )}
        </section>
      </div>

      {approving && letter && (
        <ApproveDialog
          demand={demand}
          letter={letter}
          onClose={() => setApproving(false)}
          onApproved={async () => {
            setApproving(false)
            await refreshAll()
          }}
        />
      )}
      {confirmDelete && (
        <ConfirmModal
          title={`Delete draft ${demand.demand_code}?`}
          confirmLabel="Delete draft"
          danger
          busy={deleting}
          onConfirm={deleteDraft}
          onClose={() => setConfirmDelete(false)}
        >
          <p>The draft, its chat and its files are deleted. The ID {demand.demand_code} becomes free for the next new letter.</p>
        </ConfirmModal>
      )}
    </div>
  )
}
