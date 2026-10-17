from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select

from app.deps import AdminUser, CurrentUser, DbSession
from app.errors import ProblemError
from app.modules.ai_admin.models import Letterhead
from app.modules.demands.models import DemandLetter, StoredFile
from app.modules.letters.models import LetterVersion
from app.modules.storage import StorageDep, StorageError

router = APIRouter(tags=["letters"])

INLINE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}


class LetterOut(BaseModel):
    version_no: int
    source: str
    content: dict
    missing_fields: list | None
    created_at: datetime
    docx_file_id: int
    demand_code: str
    lifecycle: str
    approved_at: datetime | None
    letterhead: dict | None


async def _latest(db, demand_id: int) -> tuple[DemandLetter, LetterVersion]:
    demand = await db.get(DemandLetter, demand_id)
    if demand is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    version = (await db.execute(
        select(LetterVersion).where(LetterVersion.demand_id == demand_id)
        .order_by(LetterVersion.version_no.desc()).limit(1)
    )).scalar_one_or_none()
    if version is None:
        raise ProblemError(404, "no-letter-yet", "No letter generated yet",
                           "Open the chat and send the inquiry to generate the letter.")
    return demand, version


@router.get("/demands/{demand_id}/letter", response_model=LetterOut)
async def latest_letter(demand_id: int, _: CurrentUser, db: DbSession):
    """The newest version of the letter, for the read-only preview."""
    demand, version = await _latest(db, demand_id)
    letterhead = None
    if version.letterhead_id:
        lh = await db.get(Letterhead, version.letterhead_id)
        letterhead = {"header_file_id": lh.header_file_id, "footer_file_id": lh.footer_file_id}
    return LetterOut(
        version_no=version.version_no, source=version.source, content=version.content,
        missing_fields=version.missing_fields, created_at=version.created_at,
        docx_file_id=version.docx_file_id, demand_code=demand.demand_code,
        lifecycle=demand.lifecycle, approved_at=demand.approved_at, letterhead=letterhead,
    )


async def _send_file(storage, f: StoredFile, *, download_name: str | None = None) -> Response:
    try:
        data = await storage.read(f.storage_key)
    except StorageError:
        raise ProblemError(404, "file-missing", "File not found in storage")
    inline = f.mime_type in INLINE_TYPES and download_name is None
    name = download_name or f.original_filename
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=f.mime_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/demands/{demand_id}/docx")
async def download_latest_docx(demand_id: int, _: CurrentUser, db: DbSession, storage: StorageDep):
    """Download the newest version as .docx (the list's download icon)."""
    demand, version = await _latest(db, demand_id)
    f = await db.get(StoredFile, version.docx_file_id)
    return await _send_file(storage, f, download_name=f"{demand.demand_code}_v{version.version_no}.docx")


@router.get("/files/{file_id}")
async def get_file(file_id: int, _: CurrentUser, db: DbSession, storage: StorageDep):
    """A stored file: attachments, pictures from JDs, letterhead images, generated letters."""
    f = await db.get(StoredFile, file_id)
    if f is None:
        raise ProblemError(404, "file-not-found", "File not found")
    return await _send_file(storage, f)


# ---------------- versions, approval, uploads (Milestone 4) ----------------

from typing import Annotated  # noqa: E402

from fastapi import File, UploadFile, status  # noqa: E402

from app.modules.letters import service as letters_service  # noqa: E402


class ApproveIn(BaseModel):
    version_no: int


class SendBackIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class VersionRef(BaseModel):
    version_no: int
    source: str
    created_by: str
    created_at: datetime
    missing_count: int
    restored_from_no: int | None


@router.post("/demands/{demand_id}/submit", status_code=status.HTTP_204_NO_CONTENT)
async def submit_letter(demand_id: int, body: ApproveIn, current: CurrentUser, db: DbSession):
    """Send the newest version to the CRM admin for approval (409 if a newer one exists)."""
    await letters_service.submit(db, demand_id=demand_id, user=current.user, version_no=body.version_no)


@router.post("/demands/{demand_id}/send-back", status_code=status.HTTP_204_NO_CONTENT)
async def send_back_letter(demand_id: int, body: SendBackIn, current: AdminUser, db: DbSession):
    """Admin: return a letter waiting for approval to the drafts."""
    await letters_service.send_back(db, demand_id=demand_id, user=current.user, reason=body.reason)


@router.post("/demands/{demand_id}/approve")
async def approve_letter(demand_id: int, body: ApproveIn, current: AdminUser, db: DbSession,
                         storage: StorageDep):
    """Admin: approve a letter that was sent for approval. Send the version you looked at:
    409 if a newer one exists.

    Writes the approval date into the header, removes the DRAFT mark (saved as a new version),
    and moves the letter to the demand list.
    """
    result = await letters_service.approve(db, storage, demand_id=demand_id, user=current.user,
                                           version_no=body.version_no)
    return result


@router.get("/demands/{demand_id}/versions", response_model=dict[str, list[VersionRef]])
async def list_versions(demand_id: int, _: CurrentUser, db: DbSession):
    return {"items": await letters_service.list_versions(db, demand_id)}


@router.get("/demands/{demand_id}/versions/{version_no}", response_model=LetterOut)
async def get_version(demand_id: int, version_no: int, _: CurrentUser, db: DbSession):
    demand = await db.get(DemandLetter, demand_id)
    if demand is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    version = await letters_service.get_version(db, demand_id, version_no)
    letterhead = None
    if version.letterhead_id:
        lh = await db.get(Letterhead, version.letterhead_id)
        letterhead = {"header_file_id": lh.header_file_id, "footer_file_id": lh.footer_file_id}
    return LetterOut(
        version_no=version.version_no, source=version.source, content=version.content,
        missing_fields=version.missing_fields, created_at=version.created_at,
        docx_file_id=version.docx_file_id, demand_code=demand.demand_code,
        lifecycle=demand.lifecycle, approved_at=demand.approved_at, letterhead=letterhead,
    )


@router.get("/demands/{demand_id}/versions/{version_no}/docx")
async def download_version(demand_id: int, version_no: int, _: CurrentUser, db: DbSession, storage: StorageDep):
    demand = await db.get(DemandLetter, demand_id)
    if demand is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")
    version = await letters_service.get_version(db, demand_id, version_no)
    f = await db.get(StoredFile, version.docx_file_id)
    return await _send_file(storage, f, download_name=f"{demand.demand_code}_v{version_no}.docx")


@router.post("/demands/{demand_id}/versions/{version_no}/restore", status_code=status.HTTP_201_CREATED)
async def restore_version(demand_id: int, version_no: int, current: CurrentUser, db: DbSession,
                          storage: StorageDep, response: Response):
    """Make an old version the newest again (saved as a new version; history is kept)."""
    new_no = await letters_service.restore(db, storage, demand_id=demand_id, user=current.user,
                                           version_no=version_no)
    response.headers["Location"] = f"/api/v1/demands/{demand_id}/versions/{new_no}"
    return {"version_no": new_no}


@router.post("/demands/{demand_id}/edited-uploads", status_code=status.HTTP_201_CREATED)
async def upload_edited_letter(demand_id: int, current: CurrentUser, db: DbSession, storage: StorageDep,
                               file: Annotated[UploadFile, File()]):
    """Upload the letter after editing it in Word. The file is kept exactly as uploaded and becomes
    the newest version; its text is read so the preview and the AI's next edit start from it."""
    return await letters_service.upload_edited(db, storage, demand_id=demand_id, user=current.user, upload=file)
