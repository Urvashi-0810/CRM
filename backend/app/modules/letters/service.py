"""Letter versions: save, approve, restore, upload an edited letter."""

import hashlib
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.modules.ai_admin.models import Letterhead
from app.modules.chat.models import ChatMessage
from app.modules.demands.models import DemandLetter, StoredFile
from app.modules.jobs.models import GenerationJob
from app.modules.letters.docx_builder import BuildInput, LetterheadImages, build_docx
from app.modules.letters.docx_tools import docx_to_letter, header_codes, replace_image_ids, stamp_docx
from app.modules.letters.letter_model import Letter
from app.modules.letters.models import LetterVersion
from app.modules.storage import Storage, StorageError, demand_folder
from app.modules.users.models import User

IST = ZoneInfo("Asia/Kolkata")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_UPLOAD_BYTES = 10_000_000


async def code_of(db: AsyncSession, demand: DemandLetter) -> str:
    """The demand code, read safely: it is computed by the database, so after an update the
    ORM marks it stale and touching demand.demand_code would trigger a hidden reload."""
    return (await db.execute(select(DemandLetter.demand_code).where(DemandLetter.id == demand.id))).scalar_one()


def approval_date_of(demand: DemandLetter):
    return demand.approved_at.astimezone(IST).date() if demand.approved_at else None


async def latest_version(db: AsyncSession, demand_id: int) -> LetterVersion | None:
    return (await db.execute(
        select(LetterVersion).where(LetterVersion.demand_id == demand_id)
        .order_by(LetterVersion.version_no.desc()).limit(1)
    )).scalar_one_or_none()


async def get_version(db: AsyncSession, demand_id: int, version_no: int) -> LetterVersion:
    version = (await db.execute(
        select(LetterVersion).where(LetterVersion.demand_id == demand_id, LetterVersion.version_no == version_no)
    )).scalar_one_or_none()
    if version is None:
        raise ProblemError(404, "version-not-found", "Version not found")
    return version


async def save_version(
    db: AsyncSession,
    storage: Storage,
    demand: DemandLetter,
    *,
    docx: bytes,
    content: dict,
    missing: list,
    source: str,
    created_by: int,
    file: StoredFile | None = None,
    prompt_version_id: int | None = None,
    letterhead_id: int | None = None,
    job_id: int | None = None,
    restored_from_no: int | None = None,
) -> LetterVersion:
    """Store a new version (append-only). Pass `file` to use an already-stored .docx."""
    number = (await db.execute(
        select(func.coalesce(func.max(LetterVersion.version_no), 0)).where(LetterVersion.demand_id == demand.id)
    )).scalar_one() + 1
    if file is None:
        code = await code_of(db, demand)
        key = f"{demand_folder(code)}/versions/v{number}-{uuid.uuid4().hex[:8]}.docx"
        await storage.write(key, docx)
        file = StoredFile(
            demand_id=demand.id, kind="generated_docx", storage_key=key,
            original_filename=f"{code}_v{number}.docx", mime_type=DOCX_MIME,
            size_bytes=len(docx), sha256=hashlib.sha256(docx).hexdigest(), uploaded_by=created_by,
        )
        db.add(file)
        await db.flush()
    version = LetterVersion(
        demand_id=demand.id, version_no=number, source=source, content=content, missing_fields=missing,
        docx_file_id=file.id, prompt_version_id=prompt_version_id, letterhead_id=letterhead_id,
        job_id=job_id, created_by=created_by, restored_from_no=restored_from_no,
    )
    db.add(version)
    await db.flush()
    return version


async def active_letterhead(db: AsyncSession, storage: Storage) -> tuple[Letterhead | None, LetterheadImages | None]:
    lh = (await db.execute(select(Letterhead).where(Letterhead.is_active))).scalar_one_or_none()
    if lh is None:
        return None, None
    header = await db.get(StoredFile, lh.header_file_id)
    footer = await db.get(StoredFile, lh.footer_file_id)
    return lh, LetterheadImages(await storage.read(header.storage_key), await storage.read(footer.storage_key))


async def rebuild_docx(db: AsyncSession, storage: Storage, demand: DemandLetter, content: dict) -> tuple[bytes, int | None]:
    """Build the .docx from the letter model with the active letterhead."""
    letter = Letter.model_validate(content)
    images: dict[str, bytes] = {}
    for b in letter.blocks:
        if b.type == "image" and b.image_id and b.image_id not in images:
            f = await db.get(StoredFile, int(b.image_id.split("-")[1]))
            if f is not None:
                images[b.image_id] = await storage.read(f.storage_key)
    lh, lh_images = await active_letterhead(db, storage)
    docx = build_docx(BuildInput(
        letter=letter, demand_code=await code_of(db, demand), approval_date=approval_date_of(demand),
        is_draft=demand.lifecycle == "draft", letterhead=lh_images, images=images,
    ))
    return docx, lh.id if lh else None


async def _stamped_or_rebuilt(db, storage, demand: DemandLetter, version: LetterVersion) -> tuple[bytes, bool, int | None]:
    """The version's .docx with the header Date/DRAFT matching the letter's state.
    Returns (docx, rebuilt, letterhead_id)."""
    source_file = await db.get(StoredFile, version.docx_file_id)
    original = await storage.read(source_file.storage_key)
    stamped = stamp_docx(original, approval_date=approval_date_of(demand), is_draft=demand.lifecycle == "draft")
    if stamped is not None:
        return stamped, False, version.letterhead_id
    docx, lh_id = await rebuild_docx(db, storage, demand, version.content)
    return docx, True, lh_id


async def _lock_demand(db: AsyncSession, demand_id: int) -> DemandLetter:
    demand = (await db.execute(
        select(DemandLetter).where(DemandLetter.id == demand_id).with_for_update()
    )).scalar_one_or_none()
    if demand is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    busy = (await db.execute(
        select(GenerationJob.id).where(
            GenerationJob.demand_id == demand_id, GenerationJob.state.in_(("queued", "running"))
        )
    )).first()
    if busy:
        raise ProblemError(409, "job-in-progress", "The AI is still working on this letter",
                           "Wait until the current reply is ready.")
    return demand


def _event(db, demand_id: int, user_id: int, body: str, **data) -> None:
    db.add(ChatMessage(demand_id=demand_id, sender="assistant", kind="event", author_id=user_id,
                       body=body, data=data or None))


def _bump(demand: DemandLetter) -> None:
    demand.row_version += 1
    demand.updated_at = datetime.now(UTC)


# ---------------- approve ----------------


async def approve(db: AsyncSession, storage: Storage, *, demand_id: int, user: User, version_no: int) -> dict:
    demand = await _lock_demand(db, demand_id)
    if demand.lifecycle == "approved":
        raise ProblemError(409, "already-approved", "This letter is already approved")
    latest = await latest_version(db, demand_id)
    if latest is None:
        raise ProblemError(422, "no-letter-yet", "There is no letter to approve yet",
                           "Generate the letter in the chat first.")
    if latest.version_no != version_no:
        raise ProblemError(
            409, "stale-version", "A newer version exists",
            f"You were looking at version {version_no}, but version {latest.version_no} is the newest. "
            "Check it, then approve.",
        )

    demand.lifecycle = "approved"
    demand.approved_at = datetime.now(UTC)
    demand.approved_by = user.id
    try:
        docx, rebuilt, lh_id = await _stamped_or_rebuilt(db, storage, demand, latest)
        version = await save_version(
            db, storage, demand, docx=docx, content=latest.content, missing=latest.missing_fields or [],
            source="approval_stamp", created_by=user.id, prompt_version_id=latest.prompt_version_id,
            letterhead_id=lh_id,
        )
    except StorageError:
        await db.rollback()
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable", "Nothing was approved. Try again.")
    _bump(demand)
    note = f"Approved by {user.display_name.rstrip('.')}. Version {version.version_no} carries the approval date."
    if rebuilt:
        note += " (The letter's header was missing, so the document was rebuilt with the letterhead.)"
    _event(db, demand.id, user.id, note, version_no=version.version_no, action="approved")
    await db.commit()
    return {"version_no": version.version_no, "rebuilt": rebuilt}


# ---------------- restore ----------------


async def restore(db: AsyncSession, storage: Storage, *, demand_id: int, user: User, version_no: int) -> int:
    demand = await _lock_demand(db, demand_id)
    old = await get_version(db, demand_id, version_no)
    latest = await latest_version(db, demand_id)
    if latest and latest.version_no == version_no:
        raise ProblemError(409, "already-latest", "This is already the newest version")
    try:
        docx, _, lh_id = await _stamped_or_rebuilt(db, storage, demand, old)
        version = await save_version(
            db, storage, demand, docx=docx, content=old.content, missing=old.missing_fields or [],
            source="restored", created_by=user.id, prompt_version_id=old.prompt_version_id,
            letterhead_id=lh_id, restored_from_no=version_no,
        )
    except StorageError:
        await db.rollback()
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable")
    _bump(demand)
    _event(db, demand.id, user.id,
           f"{user.display_name} restored version {version_no} as version {version.version_no}.",
           version_no=version.version_no, action="restored")
    await db.commit()
    return version.version_no


# ---------------- upload an edited letter ----------------


async def upload_edited(db: AsyncSession, storage: Storage, *, demand_id: int, user: User,
                        upload: UploadFile) -> dict:
    name = upload.filename or "letter.docx"
    if not name.lower().endswith(".docx"):
        raise ProblemError(415, "unsupported-file-type", "Upload the letter as a Word file (.docx)",
                           "In Word, use File → Save As → Word Document (.docx).")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ProblemError(413, "file-too-large", "File too large",
                           f'"{name}" is larger than 10.0 MB. Compress large pictures in Word and save again.')
    try:
        codes = header_codes(data)
        letter, found_images = docx_to_letter(data)
    except Exception:
        raise ProblemError(422, "file-unreadable", "The file could not be read",
                           f'"{name}" seems damaged or is not a Word document. Re-save it in Word and try again.')

    demand = await _lock_demand(db, demand_id)
    code = demand.demand_code
    others = codes - {code}
    if others and code not in codes:
        raise ProblemError(
            422, "wrong-letter", "This file belongs to another letter",
            f"Its header shows {', '.join(sorted(others))}, but this is {code}. "
            "Check you picked the right file.",
        )
    if not letter.blocks:
        raise ProblemError(422, "empty-letter", "The uploaded letter is empty")
    if await latest_version(db, demand_id) is None:
        raise ProblemError(409, "no-letter-yet", "Generate the letter first",
                           "Upload an edited letter after the first version has been generated.")

    folder = demand_folder(code)
    try:
        key = f"{folder}/uploads/{uuid.uuid4().hex[:8]}-edited.docx"
        await storage.write(key, data)
        upload_message = ChatMessage(demand_id=demand.id, sender="user", kind="text", author_id=user.id,
                                     body="Uploaded an edited letter.")
        db.add(upload_message)
        await db.flush()
        file = StoredFile(
            demand_id=demand.id, message_id=upload_message.id, kind="edited_upload", storage_key=key,
            original_filename=name, mime_type=DOCX_MIME, size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user.id,
        )
        db.add(file)
        await db.flush()
        mapping: dict[str, str] = {}
        for i, img in enumerate(found_images, start=1):
            ext = img.mime.split("/")[-1].replace("jpeg", "jpg")
            img_key = f"{folder}/images/upload{file.id}-{i}.{ext}"
            await storage.write(img_key, img.data)
            stored = StoredFile(
                demand_id=demand.id, message_id=upload_message.id, kind="extracted_image", storage_key=img_key,
                original_filename=f"{name} — picture {i}", mime_type=img.mime, size_bytes=len(img.data),
                sha256=hashlib.sha256(img.data).hexdigest(), uploaded_by=user.id,
                extracted={"source_file_id": file.id, "width": img.width, "height": img.height, "from_edited": True},
            )
            db.add(stored)
            await db.flush()
            mapping[img.placeholder] = f"img-{stored.id}"
        letter = replace_image_ids(letter, mapping)
        # The file keeps its own header; when it carries this letter's header we record the active
        # letterhead so the in-browser preview shows it too.
        lh_id = None
        if code in codes:
            lh_id = (await db.execute(select(Letterhead.id).where(Letterhead.is_active))).scalar_one_or_none()
        version = await save_version(
            db, storage, demand, docx=data, content=letter.model_dump(), missing=letter.missing_markers(),
            source="uploaded_edit", created_by=user.id, file=file, letterhead_id=lh_id,
        )
    except StorageError:
        await db.rollback()
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable")
    upload_message.data = {"version_no": version.version_no}
    upload_message.body = f"Uploaded an edited letter → version {version.version_no}."
    _bump(demand)
    version_no = version.version_no
    await db.commit()
    return {"version_no": version_no, "header_found": code in codes}


async def list_versions(db: AsyncSession, demand_id: int) -> list[dict]:
    if await db.get(DemandLetter, demand_id) is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    rows = (await db.execute(
        select(LetterVersion, User.display_name)
        .join(User, User.id == LetterVersion.created_by)
        .where(LetterVersion.demand_id == demand_id)
        .order_by(LetterVersion.version_no.desc())
    )).all()
    return [
        {"version_no": v.version_no, "source": v.source, "created_by": name, "created_at": v.created_at,
         "missing_count": len(v.missing_fields or []), "restored_from_no": v.restored_from_no}
        for v, name in rows
    ]
