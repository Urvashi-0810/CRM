"""What the worker does for one chat job: build the AI request, call it, act on the reply."""

import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import ProblemError
from app.modules.ai_admin.models import PromptVersion, ReferenceLetter
from app.modules.ai_admin.spend import ensure_within_cap
from app.modules.chat.models import ChatMessage
from app.modules.chat.service import INPUT_KINDS, KIND_LABELS
from app.modules.demands.models import DemandLetter, DemandTrade, StoredFile
from app.modules.jobs.models import GenerationJob
from app.modules.letters import service as letters_service
from app.modules.letters.letter_model import RESPONSE_SCHEMA, AiResponse
from app.modules.letters.models import LetterVersion
from app.modules.llm import gateway
from app.modules.llm.base import LlmError, LlmRequest, Part, Turn
from app.modules.llm.prompts import FIXED_REFUSAL, build_system_prompt
from app.modules.storage import Storage

log = logging.getLogger("worker")
IST = ZoneInfo("Asia/Kolkata")
AI_FILLABLE = ("country", "employer", "vacancy")
MAX_REFERENCE_CHARS = 60_000  # all library reference letters together


class JobFailed(Exception):
    """A failure with a message that can be shown to the user."""


# ---------------- building the request ----------------


async def _attachment_parts(storage: Storage, f: StoredFile, images: list[StoredFile]) -> list[Part]:
    ex = f.extracted or {}
    header = f"=== Attachment F{f.id} — {KIND_LABELS.get(f.kind, f.kind)}: {f.original_filename} ==="
    if f.kind == "custom_reference":
        header += "\n(Reference letter: use its FORMAT only, never its data.)"
    parts = [Part("text", text=header)]
    mode = ex.get("mode")
    if mode == "text":
        parts.append(Part("text", text=ex.get("text") or "(empty file)"))
    elif mode == "pdf":
        parts.append(Part("pdf", data=await storage.read(f.storage_key), mime="application/pdf"))
    elif mode == "image":
        if f.kind == "jd":
            parts.append(Part("text", text=f"This JD is an image: image_id=img-{f.id}"))
        parts.append(Part("image", data=await storage.read(f.storage_key), mime=f.mime_type))
    for img in images:
        ix = img.extracted or {}
        parts.append(Part("text", text=f"Picture inside this file: image_id=img-{img.id} "
                                        f"({ix.get('width')}×{ix.get('height')} px)"))
        parts.append(Part("image", data=await storage.read(img.storage_key), mime=img.mime_type))
    return parts


def _assistant_text(m: ChatMessage) -> str:
    data = m.data or {}
    if m.kind == "letter":
        return f"[Produced letter version {data.get('version_no')}] {m.body}"
    if m.kind == "questions":
        return m.body + "\n" + "\n".join(f"- {q}" for q in data.get("questions", []))
    if m.kind == "refusal":
        return FIXED_REFUSAL
    return m.body


async def build_request(
    db: AsyncSession, storage: Storage, demand: DemandLetter, prompt: PromptVersion | None
) -> tuple[LlmRequest, set[str]]:
    messages = list((await db.execute(
        select(ChatMessage).where(ChatMessage.demand_id == demand.id).order_by(ChatMessage.id)
    )).scalars())
    files = list((await db.execute(
        select(StoredFile).where(
            StoredFile.demand_id == demand.id,
            StoredFile.kind.in_(INPUT_KINDS + ("extracted_image",)),
        ).order_by(StoredFile.id)
    )).scalars())
    inputs_by_message: dict[int, list[StoredFile]] = {}
    images_by_source: dict[int, list[StoredFile]] = {}
    image_ids: set[str] = set()
    for f in files:
        if f.kind == "extracted_image":
            images_by_source.setdefault((f.extracted or {}).get("source_file_id"), []).append(f)
            image_ids.add(f"img-{f.id}")
        else:
            inputs_by_message.setdefault(f.message_id, []).append(f)
            if f.kind == "jd" and (f.extracted or {}).get("mode") == "image":
                image_ids.add(f"img-{f.id}")

    turns: list[Turn] = []
    for m in messages:
        if m.sender == "user":
            parts: list[Part] = []
            for f in inputs_by_message.get(m.id, []):
                parts += await _attachment_parts(storage, f, images_by_source.get(f.id, []))
            if m.body:
                parts.append(Part("text", text=m.body))
            turns.append(Turn("user", parts))
        elif m.kind != "error":
            turns.append(Turn("assistant", [Part("text", text=_assistant_text(m))]))

    latest = (await db.execute(
        select(LetterVersion).where(LetterVersion.demand_id == demand.id)
        .order_by(LetterVersion.version_no.desc()).limit(1)
    )).scalar_one_or_none()
    if latest and turns and turns[-1].role == "user":
        context = (
            f"CURRENT LETTER (version {latest.version_no}) — apply requested changes to this, "
            "keep everything else as it is:\n" + json.dumps(latest.content, ensure_ascii=False)
        )
        turns[-1].parts.insert(0, Part("text", text=context))

    # A reference letter attached in this chat overrides the admin's library.
    references: list[tuple[str, str]] = []
    if not any(f.kind == "custom_reference" for f in files):
        rows = (await db.execute(
            select(ReferenceLetter, StoredFile)
            .join(StoredFile, StoredFile.id == ReferenceLetter.file_id)
            .where(ReferenceLetter.is_active).order_by(ReferenceLetter.id)
        )).all()
        budget = MAX_REFERENCE_CHARS
        for ref, f in rows:
            text = ((f.extracted or {}).get("text") or "")[:budget]
            if text:
                references.append((ref.label, text))
                budget -= len(text)
            if budget <= 0:
                break
    system = build_system_prompt(prompt.body if prompt else "", references)
    return LlmRequest(system=system, turns=turns, json_schema=RESPONSE_SCHEMA), image_ids


# ---------------- acting on the reply ----------------


def _parse(text: str) -> AiResponse:
    return AiResponse.model_validate_json(text)


async def _apply_extracted(db: AsyncSession, demand: DemandLetter, response: AiResponse) -> None:
    ex = response.extracted
    if ex is None:
        return
    manual = set(demand.manual_fields or [])
    changed = False
    for field in AI_FILLABLE:
        value = getattr(ex, field)
        if field in manual or value in (None, ""):
            continue
        # The letter's "[[MISSING: …]]" placeholder is not a value: leave the field empty.
        if isinstance(value, str) and "[[MISSING" in value.upper():
            continue
        if field == "vacancy" and value < 0:
            continue
        if getattr(demand, field) != value:
            setattr(demand, field, value)
            changed = True
    if "trades" not in manual and ex.trades:
        await db.execute(delete(DemandTrade).where(DemandTrade.demand_id == demand.id))
        for pos, t in enumerate(ex.trades):
            if t.trade.strip() and t.quantity > 0:
                db.add(DemandTrade(demand_id=demand.id, project=(t.project or None), trade=t.trade.strip(),
                                   quantity=t.quantity, sort_order=pos))
        changed = True
    if changed:
        demand.row_version += 1
        demand.updated_at = datetime.now(UTC)


async def _save_version(
    db: AsyncSession, storage: Storage, demand: DemandLetter, job: GenerationJob,
    response: AiResponse, image_ids: set[str], prompt: PromptVersion | None,
) -> LetterVersion:
    letter = response.letter.normalised(image_ids)
    missing = list(dict.fromkeys(response.missing_fields + letter.missing_markers()))
    content = letter.model_dump()
    docx, letterhead_id = await letters_service.rebuild_docx(db, storage, demand, content)
    is_first = (await letters_service.latest_version(db, demand.id)) is None
    return await letters_service.save_version(
        db, storage, demand, docx=docx, content=content, missing=missing,
        source="generated" if is_first else "prompt_edit", created_by=job.requested_by,
        prompt_version_id=prompt.id if prompt else None, letterhead_id=letterhead_id, job_id=job.id,
    )


async def run_job(
    job_id: int, *, sessionmaker: async_sessionmaker, storage: Storage, settings: Settings
) -> None:
    """Process one claimed job end to end. Never raises: failures are recorded on the job."""
    async with sessionmaker() as db:
        job = await db.get(GenerationJob, job_id)
        if job is None or job.state != "running":
            return
        demand_id = job.demand_id
        try:
            await _run(db, job, sessionmaker=sessionmaker, storage=storage, settings=settings)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            if isinstance(exc, JobFailed):
                user_message = str(exc)
            elif isinstance(exc, ProblemError):
                user_message = f"{exc.title}. {exc.detail or ''}".strip()
            else:
                log.exception("job %s crashed", job_id)
                user_message = "Something went wrong while preparing the reply. Please try again."
            job = await db.get(GenerationJob, job_id)
            if job is None:  # draft deleted meanwhile
                return
            note = ChatMessage(demand_id=demand_id, sender="assistant", kind="error", body=user_message,
                               job_id=job.id)
            db.add(note)
            await db.flush()
            job.state, job.error = "failed", user_message
            job.finished_at, job.lease_until = datetime.now(UTC), None
            job.result_message_id = note.id
            await db.commit()


async def _run(db: AsyncSession, job: GenerationJob, *, sessionmaker, storage, settings) -> None:
    demand = await db.get(DemandLetter, job.demand_id)
    config = await gateway.active_provider(db, settings)
    if config is None:
        raise JobFailed("The AI is not set up. Ask the admin to configure it in Admin → AI settings.")
    try:
        await ensure_within_cap(db)
    except ProblemError as exc:
        raise JobFailed(f"{exc.title}. {exc.detail}")
    adapter = gateway.make_adapter(config, settings)
    prompt = (await db.execute(select(PromptVersion).where(PromptVersion.is_active))).scalar_one_or_none()
    request, image_ids = await build_request(db, storage, demand, prompt)
    await db.commit()  # release reads before the long AI call

    response: AiResponse | None = None
    for attempt in range(2):  # one retry if the reply doesn't match the schema
        try:
            result = await gateway.call_llm(sessionmaker, adapter, request, model=config.model,
                                            job_id=job.id, demand_id=demand.id)
        except LlmError as exc:
            if exc.kind == "auth":
                raise JobFailed(str(exc))
            if exc.kind == "bad_request":
                raise JobFailed(f"The AI provider refused the request: {exc}")
            raise JobFailed("The AI service is busy or unreachable right now. Please send your "
                            "message again in a few minutes.")
        try:
            response = _parse(result.text)
            if response.action == "letter" and response.letter is None:
                raise ValueError("action 'letter' without a letter")
            break
        except (ValidationError, ValueError) as exc:
            await gateway.log_invalid_output(sessionmaker, provider=config.provider, model=config.model,
                                             job_id=job.id, demand_id=demand.id, error=str(exc)[:500])
            if result.stop_reason in ("max_tokens", "FinishReason.MAX_TOKENS"):
                raise JobFailed("The letter is too long for one reply. Try splitting the request "
                                "(for example, fewer projects per letter).")
    if response is None:
        raise JobFailed("The AI's reply could not be understood. Please send your message again.")

    # Re-lock the demand for writing (it may have changed during the AI call).
    demand = (await db.execute(
        select(DemandLetter).where(DemandLetter.id == job.demand_id).with_for_update()
    )).scalar_one_or_none()
    job = (await db.execute(
        select(GenerationJob).where(GenerationJob.id == job.id).with_for_update()
    )).scalar_one_or_none()
    if demand is None or job is None or job.state != "running":
        return

    data: dict = {}
    version_no = None
    if response.action == "refuse":
        kind, body = "refusal", FIXED_REFUSAL
    elif response.action == "ask":
        kind, body = "questions", response.message or "I need a few details before writing the letter:"
        data["questions"] = response.questions
    elif response.action == "answer":
        kind, body = "answer", response.message
    else:
        version = await _save_version(db, storage, demand, job, response, image_ids, prompt)
        await _apply_extracted(db, demand, response)
        kind, body = "letter", response.message or f"Letter version {version.version_no} is ready."
        version_no = version.version_no
        data = {"version_no": version_no, "missing_fields": version.missing_fields}

    reply = ChatMessage(demand_id=demand.id, sender="assistant", kind=kind, body=body, data=data or None,
                        job_id=job.id)
    db.add(reply)
    await db.flush()
    job.state, job.finished_at, job.lease_until = "succeeded", datetime.now(UTC), None
    job.result_message_id, job.result_version_no = reply.id, version_no
    await db.commit()
