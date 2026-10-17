# Demand Letter CRM — Phase 1 (Milestones 1–4)

Login, profiles and admin (M1) · demand register (M2) · AI chat that writes the demand letter (M3) ·
**approve, edit in Word, versions, reference letters, AI budget (M4)**.

## What works now

**Milestone 4 — approve, edit, versions, budget**
- **Approve** (above the preview): writes today's date (India time) into the letter's *Date :*, removes the DRAFT
  mark and moves the letter from "Yet to be approved" to the demand list with *approved by*. If fields are still
  marked *to be filled*, a warning lists them and **Approve anyway** is offered. The approval date never changes
  afterwards; edits after approval create new versions straight away.
- **Edit → Describe the change in the chat** (prompt edit), or **Edit → Edit in Word, then upload**: download the
  .docx, edit it in Word, upload it. The uploaded file is kept **exactly as saved** and becomes the newest
  version; the AI's next edit starts from it (text, tables and pictures are read back). A file whose header shows
  another demand's ID is refused.
- **Versions**: every version (generated, prompt edit, uploaded from Word, restored, approval stamp) with who and
  when; view any of them, download its .docx, or **Restore** it (restoring makes a new newest version — nothing is
  ever overwritten).
- Approvals, restores and uploads appear in the chat as small event lines.
- **Demand list**: clicking a row opens a read-only preview of the letter; the download icon gets the newest .docx.
- **Admin → AI settings → Reference letters**: a library of sample letters (.docx / .pdf / .txt) the AI uses for
  format only. A reference letter attached in a chat takes priority: the library is then not sent for that letter.
- **Admin → Usage & budget**: a monthly AI spend limit that can be switched off at any time, spend this month,
  and usage per month (cost per day, per provider/model, tokens). When the limit is reached, new chat messages
  get a clear "monthly AI budget reached" message until the month ends.

**Milestone 3 — the letter chat**
- **+ Add Demand Letter** opens a chat for that letter (one chat = one letter).
- Attach files and mark each one as **Inquiry**, **JD** or **Reference letter** (format only). Supported:
  Word (.docx), Excel (.xlsx), CSV, TXT, PDF, PNG/JPG/WEBP/GIF. Type instructions, press **Enter**.
- The assistant reads everything, **asks about missing or unclear details** before writing, and **never invents**
  information: anything still unknown appears in the letter as a yellow *[Field — to be filled]* marker and is
  listed in the chat.
- **Generating…** runs in the background worker: you can close the page; the reply is saved in the chat.
- The letter appears in a **live preview** next to the chat and can be **downloaded as .docx** with the
  letterhead header/footer, the Demand Order ID, the Date (filled on approval) and a red **DRAFT** mark.
- **Prompt edits**: ask for changes in the chat; each reply is a new version built from the latest one.
  Editing an approved letter also creates a new version straight away; its approval date stays.
- **Questions** about the letter or its files are answered without changing it.
- **Anything unrelated** gets a fixed reply: *"I can only help with demand letters…"*.
- The AI fills **country, employer, vacancy and positions** on the list. Fields a person edited by hand are never
  overwritten by the AI.
- Relevant **pictures from the JD** (images inside Word/Excel JDs, or a JD that is itself an image) can be placed
  in the letter by the AI.
- **"File too large"** messages: over 10 MB per file, over 20 MB of files per letter, more than 20 images per
  letter, images over 8000 px, PDFs over 100 pages, or Excel sheets over 2,000 rows.
- **Admin → AI settings**: choose **Claude** or **Gemini** and the model, enter the **API key** (stored encrypted,
  only the last 4 characters are ever shown), edit the **base prompt** (every save is a version; older versions can
  be restored), upload the **letterhead** header and footer images.
- Every AI call is logged with tokens and cost (shown to the admin in Milestone 4 together with the spend cap).

**Milestone 2 — demand register**
- Lowest-free demand IDs (AA00001 … AA99999, AB00001 …), one folder per demand, "Yet to be approved" drafts with
  *Continue chat* and *Delete* (folder first, then the draft; the ID is reused), demand list with search, filters,
  sorting, numbered pages, Excel export, details panel with conflict detection. Approved letters can't be deleted.
- The list's **download icon** now downloads the newest .docx.

**Milestone 1 — foundation**
- Login with server-side sessions, My Profile (name changes need admin approval), own password change,
  admin page behind a separate password: users, roles, password resets, name-change approvals.

---

## Run with Docker (recommended)

Requires Docker Desktop (or Docker Engine + Compose v2.24+).

```bash
cp .env.example .env
docker compose run --rm api python -m scripts.generate_secret_key   # copy the output into .env as APP_SECRET_KEY=...
docker compose up --build -d                                         # db · api · worker · web
docker compose run --rm api python -m scripts.bootstrap              # first time: your user + admin password
```

Open **http://localhost:5173**, sign in, then **Admin → AI settings**:
1. Add a provider (Claude or Gemini), its model and API key, and click **Make active**.
2. Upload the letterhead **header** and **footer** images (PNG/JPG, without the "Demand Order ID" and "Date" text).
3. Replace the starting **base prompt** with the client's prompt.

- API docs (Swagger): http://localhost:8000/api/docs
- Upgrading from an earlier milestone: just `docker compose up --build -d`; the database is updated automatically.

### Trying it without an API key (development only)

Set `LLM_ALLOW_TEST_PROVIDER=true` in `.env` and restart. Admin → AI settings then offers **"Test — no AI"**, which
returns canned letters built from the first table in your files, so the chat → preview → download flow can be
tried. Never enable this on the client's server.

### Demo data for the list (development only)

```bash
docker compose run --rm api python -m scripts.seed_demo      # 40 approved + 3 draft sample letters
```

## Run without Docker

Requires Python 3.12+, Node 22+, PostgreSQL 16.

```bash
createdb crm && createdb crm_test
cp .env.example .env                         # set DATABASE_URL, then APP_SECRET_KEY (see below)

# backend
cd backend
(Note: copy the .env file to backend folder also)
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env .env
python -m scripts.generate_secret_key        # put the output in .env as APP_SECRET_KEY=...
alembic upgrade head
python -m scripts.bootstrap
uvicorn app.main:app --reload --port 8000    # terminal 1
python -m app.worker                         # terminal 2 — the AI jobs run here

# frontend (terminal 3)
cd frontend && npm install && npm run dev    # http://localhost:5173
```

## Tests

```bash
cd backend
pytest                      # uses TEST_DATABASE_URL; the test database is wiped on every run
docker compose run --rm api pytest
```

98 tests. Milestone 4 adds: approval (date stamped, DRAFT removed, list), approve rules (no letter yet, AI
busy, stale version), edits after approval, version history and restore, uploading an edited Word file
(read back, kept byte for byte, wrong-letter refused, AI continues from it), reference letters (used, or
overridden by the chat's own), spend cap and usage (UTC month), and the four client sample inquiries end to end.

Milestone 3 added:
- reading the client's real sample inquiries and JDs (multi-project tables, shorthand like "FAT" kept as written);
- the exact requests sent to **Claude** and **Gemini** through their real SDKs (fake network, no key needed),
  and how their replies, token usage and errors (rate limit, overload, bad key) are read;
- the full flow with a scripted AI: ask → answer → letter → download, prompt edits from the latest version,
  manual fields not overwritten, fixed refusal, retries on rate limits (each attempt logged), bad API key,
  invalid AI output, JD pictures (invented image ids dropped), "file too large", a worker crash being recovered,
  deleting a draft while the AI works (blocked) and after (usage records kept);
- the .docx: letterhead, Demand Order ID, DRAFT mark, highlighted missing fields, approval date.

**Not tested here:** Docker (images can't be downloaded in this workspace; a clean `pip install` and the full test
suite were checked instead), and calls to the real Claude/Gemini services (this workspace has no API key or internet access to
them). The first real test is yours: add your key in Admin → AI settings and send one of the sample inquiries.

---

## Project layout

```
demand-crm/
├── docker-compose.yml        db · api · worker · web
├── .env.example
├── storage/                  letterhead/ · references/ · demands/<ID>/{inputs,images,versions,uploads}/
├── backend/
│   ├── alembic/versions/     0001 users · 0002 demands · 0003 chat, jobs, versions, AI settings · 0004 references, spend cap
│   ├── scripts/              bootstrap · generate_secret_key · seed_demo (dev only)
│   ├── app/
│   │   ├── main.py · worker.py (background jobs) · config.py · db.py · errors.py · security.py · deps.py
│   │   └── modules/
│   │       ├── auth/ users/ admin/            login, profiles, admin
│   │       ├── demands/ storage/              demand register, IDs, files
│   │       ├── chat/                          messages + labelled uploads + limits
│   │       ├── extraction/readers.py          Word / Excel / CSV / PDF / image reading
│   │       ├── jobs/                          queue (Postgres, leases) + what a job does
│   │       ├── llm/                           gateway, Claude + Gemini adapters, prompts, pricing, key encryption
│   │       ├── letters/                       letter model, .docx builder + reader, approve, versions, uploads
│   │       └── ai_admin/                      providers, base prompt, letterhead, reference letters, spend cap, usage
│   └── tests/  (fixtures: the client's sample inquiries and JDs)
└── frontend/src/
    ├── pages/        Login · My Profile · Demand list · Chat (with preview)
    ├── components/   Layout · drafts · details panel · LetterPreview · LetterActions (approve/edit/versions) · shared UI
    └── admin/        Users · Name-change requests · AI settings · Usage & budget · Admin password
```

## API

All routes are under `/api/v1`; errors are `application/problem+json`; every POST/PUT/PATCH/DELETE sends
`X-CSRF-Token`. Full, live documentation: http://localhost:8000/api/docs.

| Method | Route | Notes |
|---|---|---|
| POST | `/auth/login` · `/auth/logout` | session cookie |
| GET | `/me` | profile, admin status, csrf_token |
| PUT | `/me/password` | other sessions logged out |
| GET / POST | `/me/name-change-requests` | |
| GET / POST / DELETE | `/admin/session` | admin unlock |
| … | `/admin/users`, `/admin/users/{id}/password`, `/admin/name-change-requests/…`, `/admin/password` | |
| POST / GET | `/demands` | add draft (Idempotency-Key) / list with filters |
| GET / PATCH / DELETE | `/demands/{id}` | PATCH needs If-Match; DELETE 409 if approved or AI working |
| PUT | `/demands/{id}/trades` | |
| GET | `/demands/export` · `/demands/filter-options` | |
| GET | `/demands/{id}/messages` | chat history |
| POST | `/demands/{id}/messages` | multipart: `text`, `files[]`, `kinds[]` (inquiry · jd · custom_reference) → **202** + job · 409 busy / AI not set up · 413 too large · 415 type · 429 monthly budget reached |
| GET | `/demands/{id}/active-job` · `/jobs/{id}` | poll while "Generating…" |
| GET | `/demands/{id}/letter` | newest version (for the preview) · 404 none yet |
| GET | `/demands/{id}/docx` | download newest .docx |
| POST | `/demands/{id}/approve` | `{version_no}` · 409 already approved / stale version / AI working · 422 no letter yet |
| GET | `/demands/{id}/versions` · `/versions/{no}` · `/versions/{no}/docx` | history, one version, its file |
| POST | `/demands/{id}/versions/{no}/restore` | **201** new newest version · 409 already newest |
| POST | `/demands/{id}/edited-uploads` | multipart `file` (.docx) → **201** `{version_no, header_found}` · 422 wrong letter |
| GET | `/files/{id}` | attachments, JD pictures, letterhead images |
| GET | `/ai/status` | is the AI set up, active letterhead |
| … | `/admin/llm-providers`, `/admin/prompts`, `/admin/letterheads` | AI settings (admin) |
| GET / POST / PATCH / DELETE | `/admin/reference-letters` | reference letter library (admin) |
| GET / PUT | `/admin/spend-cap` | `{enabled, limit_usd}` (admin) |
| GET | `/admin/usage?month=YYYY-MM` | usage report (admin) |

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | — | PostgreSQL URL (asyncpg driver) |
| `TEST_DATABASE_URL` | — | database the tests wipe and rebuild |
| `APP_SECRET_KEY` | — | **required for AI settings**; encrypts stored API keys |
| `COOKIE_SECURE` | `true` | `false` only for `http://localhost` |
| `STORAGE_ROOT` | `./storage` | file storage |
| `MAX_FILE_MB` / `MAX_LETTER_INPUTS_MB` / `MAX_IMAGES_PER_LETTER` | 10 / 20 / 20 | upload limits |
| `WORKER_CONCURRENCY` / `JOB_LEASE_SECONDS` | 10 / 300 | worker |
| `LLM_ALLOW_TEST_PROVIDER` | `false` | development only |
| `SESSION_TTL_HOURS`, `ADMIN_SESSION_MINUTES`, `ADMIN_MAX_FAILED_ATTEMPTS`, `ADMIN_LOCKOUT_MINUTES`, `PASSWORD_MIN_LENGTH` | 12, 30, 5, 15, 6 | |

## Decisions in Milestone 3

- **The AI never writes the .docx.** It returns the letter as blocks (headings, paragraphs, lists, tables,
  images); code builds the .docx and the preview from them, so the letterhead, ID and date are always exact.
- **Structured output**: Claude via `output_config.format` (JSON schema), Gemini via `response_json_schema`. If a
  reply doesn't match, it is retried once; if the provider is busy or rate-limited, up to 4 attempts, each logged.
- **Fixed rules come first** in the instructions (scope, never invent, ask before writing, keep wording as written,
  attachments are data not instructions); the client's base prompt follows.
- **PDFs and images go to the AI as they are** (both providers read them, including scans). Word/Excel/CSV are
  converted to text and tables first.
- **Pictures from the inquiry are not offered for the letter** (they are usually signatures/logos); pictures from
  JDs are.
- **Edits always start from the newest version.** The current letter is sent with each new message; the AI
  returns the full updated letter.
- **Models**: the admin picks the model; suggestions are `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`,
  `gemini-3.8-flash`, `gemini-3.1-pro-preview`. Costs are calculated from the prices in `llm/pricing.py` (checked
  9 Oct 2026); unknown models still work, with cost recorded as unknown.
- Any logged-in user can open any stored file (attachments, letters) — fine for one internal team; revisit if the
  product is sold to several agencies.

## Decisions in Milestone 4

- **Months follow UTC** for the spend limit and usage, like the providers' billing: a new month starts on the
  1st at 00:00 UTC (05:30 India time).
- **The limit is checked before each AI call** (when a message is sent and again when the worker starts it). A
  reply already running is allowed to finish, so the month can end slightly above the limit.
- **Approval with missing fields is allowed**, with a warning listing them.
- **Approving doesn't regenerate the letter.** The newest .docx gets the date written into its header and the
  DRAFT mark removed, and is saved as a new version (*Approval stamp*). If the header was deleted in Word, the
  letter is rebuilt with the letterhead instead, and the chat says so.
- **An uploaded Word file is kept exactly as uploaded.** Only on approval is its header date stamped in place.
- Approve, restore and upload are quick, so they run immediately (not through the background worker).
- A reference letter attached in the chat replaces the admin's library for that letter; the library is limited
  to about 60,000 characters per request to keep costs predictable.
- Version files are named `v<no>-<random>.docx` so a leftover file can never block saving a new version.
