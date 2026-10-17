"""Chat messages: posting (with labelled attachments) and listing."""

import hashlib
import io
import re
import uuid
from dataclasses import dataclass

from docx import Document
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ProblemError
from app.modules.chat.models import ChatMessage
from app.modules.demands.models import DemandLetter, StoredFile
from app.modules.extraction.readers import (
    ReadResult,
    UploadRejected,
    extension_of,
    read_upload,
)
from app.modules.jobs.models import GenerationJob
from app.modules.ai_admin.spend import ensure_within_cap
from app.modules.llm.gateway import active_provider
from app.modules.storage import Storage, StorageError, demand_folder

INPUT_KINDS = ("inquiry", "jd", "custom_reference")
KIND_LABELS = {"inquiry": "Demand inquiry", "jd": "Job description", "custom_reference": "Reference letter"}
ALLOWED_BY_KIND = {
    "inquiry": {"docx", "pdf", "txt"},
    "custom_reference": {"docx", "pdf", "txt"},
    "jd": {"docx", "xlsx", "xlsm", "csv", "txt", "pdf", "png", "jpg", "jpeg", "webp", "gif"},
}
MAX_FILES_PER_MESSAGE = 10
MAX_TEXT_LENGTH = 20_000
MAX_PASTED_INQUIRY_LENGTH = 100_000
PASTED_INQUIRY_NAME = "Demand inquiry (pasted mail).docx"
# Characters XML (and so .docx) can't hold; mail clients sometimes paste them.
_XML_INVALID = re.compile(r"[\x00-\x08\x0e-\x1f￾￿]")


def pasted_text_to_docx(text: str) -> bytes:
    """A plain .docx with one paragraph per line of the pasted mail."""
    text = _XML_INVALID.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    doc = Document()
    for line in re.split(r"[\n\x0b\x0c]", text):
        doc.add_paragraph(line)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _problem(exc: UploadRejected) -> ProblemError:
    return ProblemError(exc.status, exc.slug, exc.title, exc.detail)


def _safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" .") or "file"
    return name[-120:]


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


@dataclass
class PreparedFile:
    upload_name: str
    kind: str
    data: bytes
    read: ReadResult


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise ProblemError(
            413, "file-too-large", "File too large",
            f'"{upload.filename}" is larger than {_mb(limit)}. Upload a smaller file '
            "(for example, only the pages or sheets you need).",
        )
    return data


async def post_message(
    db: AsyncSession,
    storage: Storage,
    settings: Settings,
    *,
    demand_id: int,
    user_id: int,
    text: str,
    files: list[UploadFile],
    kinds: list[str],
    inquiry_text: str = "",
) -> tuple[ChatMessage, GenerationJob]:
    text = (text or "").strip()
    inquiry_text = (inquiry_text or "").strip()
    if not text and not files and not inquiry_text:
        raise ProblemError(422, "empty-message", "Type a message or attach a file")
    if len(text) > MAX_TEXT_LENGTH:
        raise ProblemError(422, "message-too-long", "Message too long",
                           f"Keep messages under {MAX_TEXT_LENGTH:,} characters.")
    if len(inquiry_text) > MAX_PASTED_INQUIRY_LENGTH:
        raise ProblemError(422, "inquiry-too-long", "Pasted inquiry too long",
                           f"Keep the pasted mail under {MAX_PASTED_INQUIRY_LENGTH:,} characters, "
                           "or attach it as a file instead.")
    if len(files) + (1 if inquiry_text else 0) > MAX_FILES_PER_MESSAGE:
        raise ProblemError(413, "too-many-files", "Too many files",
                           f"Attach at most {MAX_FILES_PER_MESSAGE} files per message.")
    if len(kinds) != len(files) or any(k not in INPUT_KINDS for k in kinds):
        raise ProblemError(422, "file-label-missing", "Choose what each file is",
                           "Mark every attached file as Inquiry, JD or Reference letter.")

    demand = (
        await db.execute(select(DemandLetter).where(DemandLetter.id == demand_id).with_for_update())
    ).scalar_one_or_none()
    if demand is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    if await active_provider(db, settings) is None:
        raise ProblemError(
            409, "ai-not-configured", "The AI is not set up yet",
            "Ask the admin to choose an AI provider and enter its API key (Admin → AI settings).",
        )
    await ensure_within_cap(db)
    busy = (
        await db.execute(
            select(GenerationJob.id).where(
                GenerationJob.demand_id == demand_id, GenerationJob.state.in_(("queued", "running"))
            )
        )
    ).first()
    if busy:
        raise ProblemError(409, "job-in-progress", "Still working on your previous message",
                           "Wait until the current reply is ready, then send again.")

    # ---- read and validate every file before storing anything ----
    per_file = settings.max_file_mb * 1_000_000
    prepared: list[PreparedFile] = []
    if inquiry_text:
        data = pasted_text_to_docx(inquiry_text)
        try:
            read = read_upload(data, PASTED_INQUIRY_NAME, keep_images=False)
        except UploadRejected as exc:
            raise _problem(exc)
        prepared.append(PreparedFile(PASTED_INQUIRY_NAME, "inquiry", data, read))
    for upload, kind in zip(files, kinds):
        name = upload.filename or "file"
        ext = extension_of(name)
        if ext not in ALLOWED_BY_KIND[kind] and ext not in ("doc", "xls"):
            allowed = ", ".join(sorted(ALLOWED_BY_KIND[kind]))
            raise ProblemError(415, "unsupported-file-type", "This file type is not allowed here",
                               f'"{name}" can\'t be used as {KIND_LABELS[kind]}. Allowed: {allowed}.')
        data = await _read_limited(upload, per_file)
        try:
            read = read_upload(data, name, keep_images=(kind == "jd"))
        except UploadRejected as exc:
            raise _problem(exc)
        prepared.append(PreparedFile(name, kind, data, read))

    existing_bytes, existing_images = (
        await db.execute(
            select(
                func.coalesce(func.sum(StoredFile.size_bytes), 0),
                func.count().filter(
                    (StoredFile.kind == "extracted_image") | StoredFile.mime_type.like("image/%")
                ),
            ).where(
                StoredFile.demand_id == demand_id,
                StoredFile.kind.in_(INPUT_KINDS + ("extracted_image",)),
            )
        )
    ).one()
    new_bytes = sum(len(p.data) for p in prepared)
    total_limit = settings.max_letter_inputs_mb * 1_000_000
    if existing_bytes + new_bytes > total_limit:
        raise ProblemError(
            413, "letter-inputs-too-large", "Files too large for one letter",
            f"All files attached to one letter must stay under {_mb(total_limit)} together "
            f"(already attached: {_mb(existing_bytes)}, new: {_mb(new_bytes)}).",
        )
    new_images = sum((1 if p.read.mode == "image" else 0) + len(p.read.images) for p in prepared)
    if existing_images + new_images > settings.max_images_per_letter:
        raise ProblemError(
            413, "too-many-images", "Too many images",
            f"One letter can use at most {settings.max_images_per_letter} images "
            f"(including pictures inside Word/Excel files). This message would bring it to "
            f"{existing_images + new_images}.",
        )

    # ---- store ----
    message = ChatMessage(demand_id=demand_id, sender="user", kind="text", author_id=user_id, body=text)
    db.add(message)
    await db.flush()
    folder = demand_folder(demand.demand_code)
    try:
        for p in prepared:
            key = f"{folder}/inputs/{uuid.uuid4().hex[:8]}-{_safe_name(p.upload_name)}"
            await storage.write(key, p.data)
            stored = StoredFile(
                demand_id=demand_id, message_id=message.id, kind=p.kind, storage_key=key,
                original_filename=p.upload_name,
                mime_type=p.read.mime if p.read.mode != "text" else _mime_for(p.upload_name),
                size_bytes=len(p.data), sha256=hashlib.sha256(p.data).hexdigest(),
                uploaded_by=user_id,
                extracted={"mode": p.read.mode, "text": p.read.text, "pages": p.read.pages,
                           "width": p.read.width, "height": p.read.height, "mime": p.read.mime},
            )
            db.add(stored)
            await db.flush()
            for index, img in enumerate(p.read.images, start=1):
                ext = img.mime.split("/")[-1].replace("jpeg", "jpg")
                img_key = f"{folder}/images/{stored.id}-{index}.{ext}"
                await storage.write(img_key, img.data)
                db.add(StoredFile(
                    demand_id=demand_id, message_id=message.id, kind="extracted_image",
                    storage_key=img_key, original_filename=f"{p.upload_name} — picture {index}",
                    mime_type=img.mime, size_bytes=len(img.data),
                    sha256=hashlib.sha256(img.data).hexdigest(), uploaded_by=user_id,
                    extracted={"source_file_id": stored.id, "width": img.width, "height": img.height},
                ))
    except StorageError:
        await db.rollback()
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable",
                           "Your message was not sent. Try again in a moment.")

    job = GenerationJob(demand_id=demand_id, message_id=message.id, requested_by=user_id)
    db.add(job)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ProblemError(409, "job-in-progress", "Still working on your previous message")
    message.job_id = job.id
    await db.commit()
    await db.refresh(message)
    await db.refresh(job)
    return message, job


def _mime_for(filename: str) -> str:
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        "csv": "text/csv",
        "txt": "text/plain",
    }.get(extension_of(filename), "application/octet-stream")


async def list_messages(db: AsyncSession, demand_id: int, after_id: int | None) -> list[dict]:
    query = select(ChatMessage).where(ChatMessage.demand_id == demand_id).order_by(ChatMessage.id)
    if after_id:
        query = query.where(ChatMessage.id > after_id)
    messages = list((await db.execute(query)).scalars())
    if not messages:
        return []
    files = (
        await db.execute(
            select(StoredFile)
            .where(StoredFile.message_id.in_([m.id for m in messages]), StoredFile.kind.in_(INPUT_KINDS))
            .order_by(StoredFile.id)
        )
    ).scalars()
    by_message: dict[int, list[dict]] = {}
    for f in files:
        by_message.setdefault(f.message_id, []).append({
            "id": f.id, "name": f.original_filename, "kind": f.kind,
            "size_bytes": f.size_bytes, "mime_type": f.mime_type,
        })
    authors = {}
    author_ids = {m.author_id for m in messages if m.author_id}
    if author_ids:
        from app.modules.users.models import User

        rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(author_ids)))
        authors = dict(rows.all())
    return [
        {
            "id": m.id, "sender": m.sender, "kind": m.kind, "body": m.body, "data": m.data,
            "author": authors.get(m.author_id), "job_id": m.job_id, "created_at": m.created_at,
            "files": by_message.get(m.id, []),
        }
        for m in messages
    ]
