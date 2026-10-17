from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel

from app.deps import AppSettings, CurrentUser, DbSession
from app.errors import ProblemError
from app.modules.chat import service
from app.modules.demands.models import DemandLetter
from app.modules.jobs.models import GenerationJob
from app.modules.storage import StorageDep

router = APIRouter(tags=["chat"])


class FileRef(BaseModel):
    id: int
    name: str
    kind: str
    size_bytes: int
    mime_type: str


class MessageOut(BaseModel):
    id: int
    sender: str
    kind: str
    body: str
    data: dict | None
    author: str | None
    job_id: int | None
    created_at: datetime
    files: list[FileRef]


class JobOut(BaseModel):
    id: int
    demand_id: int
    state: str
    error: str | None
    result_message_id: int | None
    result_version_no: int | None
    created_at: datetime
    finished_at: datetime | None


class PostedOut(BaseModel):
    message: MessageOut
    job: JobOut


async def _demand_or_404(db, demand_id: int) -> None:
    if await db.get(DemandLetter, demand_id) is None:
        raise ProblemError(404, "demand-not-found", "Demand letter not found")


@router.get("/demands/{demand_id}/messages", response_model=dict[str, list[MessageOut]])
async def list_messages(
    demand_id: int, _: CurrentUser, db: DbSession,
    after_id: Annotated[int | None, Query(ge=0)] = None,
):
    await _demand_or_404(db, demand_id)
    return {"items": await service.list_messages(db, demand_id, after_id)}


@router.post("/demands/{demand_id}/messages", response_model=PostedOut, status_code=status.HTTP_202_ACCEPTED)
async def post_message(
    demand_id: int,
    current: CurrentUser,
    db: DbSession,
    storage: StorageDep,
    settings: AppSettings,
    response: Response,
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    kinds: Annotated[list[str] | None, Form()] = None,
    inquiry_text: Annotated[str, Form()] = "",
):
    """Send a chat message, optionally with files. Each file needs a label in `kinds`
    (inquiry | jd | custom_reference), in the same order as `files`.

    `inquiry_text` is a pasted demand-inquiry mail: the server saves it as a .docx and
    attaches it as the inquiry, exactly as if the user had uploaded that file.

    Returns 202: the reply is produced by the worker; poll GET /jobs/{id}.
    """
    message, job = await service.post_message(
        db, storage, settings, demand_id=demand_id, user_id=current.user.id,
        text=text, files=files or [], kinds=kinds or [], inquiry_text=inquiry_text,
    )
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    items = await service.list_messages(db, demand_id, message.id - 1)
    return PostedOut(message=MessageOut(**items[0]), job=JobOut.model_validate(job, from_attributes=True))


@router.get("/demands/{demand_id}/active-job", response_model=JobOut | None)
async def active_job(demand_id: int, _: CurrentUser, db: DbSession):
    """The job still being worked on for this letter, if any (to resume the spinner after a reload)."""
    from sqlalchemy import select

    job = (await db.execute(
        select(GenerationJob).where(
            GenerationJob.demand_id == demand_id, GenerationJob.state.in_(("queued", "running"))
        )
    )).scalar_one_or_none()
    return JobOut.model_validate(job, from_attributes=True) if job else None


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int, _: CurrentUser, db: DbSession):
    job = await db.get(GenerationJob, job_id)
    if job is None:
        raise ProblemError(404, "job-not-found", "Job not found")
    return JobOut.model_validate(job, from_attributes=True)
