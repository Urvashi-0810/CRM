"""Admin → AI settings: provider + API key, base prompt, letterhead. Plus /ai/status for users."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select, update

from app.deps import AdminUser, AppSettings, CurrentUser, DbSession
from app.errors import ProblemError
from app.modules.ai_admin.models import Letterhead, LlmProviderConfig, PromptVersion
from app.modules.demands.models import StoredFile
from app.modules.extraction.readers import UploadRejected, read_image
from app.modules.llm.gateway import active_provider
from app.modules.llm.secrets import encrypt_api_key
from app.modules.storage import StorageDep, StorageError

router = APIRouter(tags=["admin: ai settings"])

Provider = Literal["claude", "gemini", "test"]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
ApiKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=500)]
MAX_LETTERHEAD_BYTES = 5_000_000

# Suggestions only; the admin can type any model the provider offers.
MODEL_SUGGESTIONS = {
    "claude": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
    "gemini": ["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.5-flash"],
    "test": ["test"],
}


# ---------------- status for everyone ----------------


class AiStatus(BaseModel):
    configured: bool
    provider: str | None
    model: str | None
    letterhead: dict | None


@router.get("/ai/status", response_model=AiStatus)
async def ai_status(_: CurrentUser, db: DbSession, settings: AppSettings):
    config = await active_provider(db, settings)
    lh = (await db.execute(select(Letterhead).where(Letterhead.is_active))).scalar_one_or_none()
    return AiStatus(
        configured=config is not None,
        provider=config.provider if config else None,
        model=config.model if config else None,
        letterhead={"header_file_id": lh.header_file_id, "footer_file_id": lh.footer_file_id} if lh else None,
    )


# ---------------- providers ----------------


class ProviderOut(BaseModel):
    id: int
    provider: str
    model: str
    key_last4: str | None
    has_key: bool
    is_active: bool
    updated_at: datetime


class ProviderCreate(BaseModel):
    provider: Provider
    model: ModelName
    api_key: ApiKey | None = None


class ProviderUpdate(BaseModel):
    model: ModelName | None = None
    api_key: ApiKey | None = None


def _out(c: LlmProviderConfig) -> ProviderOut:
    return ProviderOut(id=c.id, provider=c.provider, model=c.model, key_last4=c.key_last4,
                       has_key=c.api_key_encrypted is not None, is_active=c.is_active, updated_at=c.updated_at)


@router.get("/admin/llm-providers")
async def list_providers(_: AdminUser, db: DbSession, settings: AppSettings):
    rows = (await db.execute(select(LlmProviderConfig).order_by(LlmProviderConfig.id))).scalars()
    providers = ["claude", "gemini"] + (["test"] if settings.llm_allow_test_provider else [])
    return {
        "items": [_out(c) for c in rows],
        "providers": providers,
        "model_suggestions": {p: MODEL_SUGGESTIONS[p] for p in providers},
    }


@router.post("/admin/llm-providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(body: ProviderCreate, admin: AdminUser, db: DbSession, settings: AppSettings):
    if body.provider == "test" and not settings.llm_allow_test_provider:
        raise ProblemError(422, "test-provider-disabled", "The test provider is disabled on this server")
    if body.provider != "test" and not body.api_key:
        raise ProblemError(422, "validation-error", "Some fields are invalid", errors=[
            {"field": "api_key", "message": "Enter the API key."}])
    config = LlmProviderConfig(provider=body.provider, model=body.model, updated_by=admin.user.id)
    if body.api_key:
        config.api_key_encrypted = encrypt_api_key(settings, body.api_key)
        config.key_last4 = body.api_key[-4:]
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return _out(config)


@router.patch("/admin/llm-providers/{config_id}", response_model=ProviderOut)
async def update_provider(config_id: int, body: ProviderUpdate, admin: AdminUser, db: DbSession,
                          settings: AppSettings):
    config = await db.get(LlmProviderConfig, config_id)
    if config is None:
        raise ProblemError(404, "provider-not-found", "Provider setting not found")
    if body.model:
        config.model = body.model
    if body.api_key:
        config.api_key_encrypted = encrypt_api_key(settings, body.api_key)
        config.key_last4 = body.api_key[-4:]
    config.updated_by, config.updated_at = admin.user.id, datetime.now(UTC)
    await db.commit()
    await db.refresh(config)
    return _out(config)


@router.post("/admin/llm-providers/{config_id}/activate", response_model=ProviderOut)
async def activate_provider(config_id: int, admin: AdminUser, db: DbSession, settings: AppSettings):
    config = await db.get(LlmProviderConfig, config_id)
    if config is None:
        raise ProblemError(404, "provider-not-found", "Provider setting not found")
    if config.provider == "test" and not settings.llm_allow_test_provider:
        raise ProblemError(422, "test-provider-disabled", "The test provider is disabled on this server")
    if config.provider != "test" and not config.api_key_encrypted:
        raise ProblemError(409, "api-key-missing", "Enter the API key before activating")
    await db.execute(update(LlmProviderConfig).values(is_active=False).where(LlmProviderConfig.is_active))
    config.is_active, config.updated_by, config.updated_at = True, admin.user.id, datetime.now(UTC)
    await db.commit()
    await db.refresh(config)
    return _out(config)


@router.delete("/admin/llm-providers/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(config_id: int, _: AdminUser, db: DbSession):
    config = await db.get(LlmProviderConfig, config_id)
    if config is None:
        raise ProblemError(404, "provider-not-found", "Provider setting not found")
    if config.is_active:
        raise ProblemError(409, "provider-active", "Activate another provider before deleting this one")
    await db.delete(config)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------- base prompt ----------------


class PromptIn(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=20_000)]


class PromptOut(BaseModel):
    id: int
    body: str
    is_active: bool
    created_at: datetime


@router.get("/admin/prompts")
async def list_prompts(_: AdminUser, db: DbSession):
    rows = (await db.execute(select(PromptVersion).order_by(PromptVersion.id.desc()).limit(50))).scalars()
    return {"items": [PromptOut.model_validate(p, from_attributes=True) for p in rows]}


@router.post("/admin/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
async def save_prompt(body: PromptIn, admin: AdminUser, db: DbSession):
    """Saving creates a new version and makes it the active one (old versions are kept)."""
    await db.execute(update(PromptVersion).values(is_active=False).where(PromptVersion.is_active))
    prompt = PromptVersion(body=body.body, is_active=True, created_by=admin.user.id)
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return PromptOut.model_validate(prompt, from_attributes=True)


@router.post("/admin/prompts/{prompt_id}/activate", response_model=PromptOut)
async def activate_prompt(prompt_id: int, _: AdminUser, db: DbSession):
    prompt = await db.get(PromptVersion, prompt_id)
    if prompt is None:
        raise ProblemError(404, "prompt-not-found", "Prompt version not found")
    await db.execute(update(PromptVersion).values(is_active=False).where(PromptVersion.is_active))
    prompt.is_active = True
    await db.commit()
    await db.refresh(prompt)
    return PromptOut.model_validate(prompt, from_attributes=True)


# ---------------- letterhead ----------------


async def _store_letterhead_image(db, storage, upload: UploadFile, kind: str, user_id: int) -> StoredFile:
    data = await upload.read(MAX_LETTERHEAD_BYTES + 1)
    name = upload.filename or kind
    if len(data) > MAX_LETTERHEAD_BYTES:
        raise ProblemError(413, "file-too-large", "File too large",
                           f'"{name}" is larger than 5 MB. Export the image smaller.')
    try:
        info = read_image(data, name)
    except UploadRejected as exc:
        raise ProblemError(exc.status, exc.slug, exc.title, exc.detail)
    if info.mime not in ("image/png", "image/jpeg"):
        raise ProblemError(415, "unsupported-file-type", "Use PNG or JPG for the letterhead")
    ext = "png" if info.mime == "image/png" else "jpg"
    key = f"letterhead/{uuid.uuid4().hex[:10]}-{kind}.{ext}"
    try:
        await storage.write(key, data)
    except StorageError:
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable")
    f = StoredFile(kind=f"letterhead_{kind}", storage_key=key, original_filename=name, mime_type=info.mime,
                   size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), uploaded_by=user_id,
                   extracted={"width": info.width, "height": info.height})
    db.add(f)
    await db.flush()
    return f


@router.get("/admin/letterheads")
async def list_letterheads(_: AdminUser, db: DbSession):
    rows = (await db.execute(select(Letterhead).order_by(Letterhead.id.desc()).limit(20))).scalars()
    return {"items": [
        {"id": r.id, "header_file_id": r.header_file_id, "footer_file_id": r.footer_file_id,
         "is_active": r.is_active, "created_at": r.created_at} for r in rows
    ]}


@router.post("/admin/letterheads", status_code=status.HTTP_201_CREATED)
async def upload_letterhead(
    admin: AdminUser, db: DbSession, storage: StorageDep,
    header: Annotated[UploadFile, File()], footer: Annotated[UploadFile, File()],
):
    """Upload header + footer images (PNG/JPG, full page width). The new pair becomes active.
    Letters already generated keep the letterhead they were made with."""
    h = await _store_letterhead_image(db, storage, header, "header", admin.user.id)
    f = await _store_letterhead_image(db, storage, footer, "footer", admin.user.id)
    await db.execute(update(Letterhead).values(is_active=False).where(Letterhead.is_active))
    lh = Letterhead(header_file_id=h.id, footer_file_id=f.id, is_active=True, created_by=admin.user.id)
    db.add(lh)
    await db.commit()
    return {"id": lh.id, "header_file_id": h.id, "footer_file_id": f.id, "is_active": True,
            "created_at": lh.created_at}


@router.post("/admin/letterheads/{letterhead_id}/activate")
async def activate_letterhead(letterhead_id: int, _: AdminUser, db: DbSession):
    lh = await db.get(Letterhead, letterhead_id)
    if lh is None:
        raise ProblemError(404, "letterhead-not-found", "Letterhead not found")
    await db.execute(update(Letterhead).values(is_active=False).where(Letterhead.is_active))
    lh.is_active = True
    await db.commit()
    return {"id": lh.id, "is_active": True}


# ---------------- spend cap + usage (Milestone 4) ----------------

from datetime import date as _date  # noqa: E402
from decimal import Decimal  # noqa: E402

from pydantic import Field  # noqa: E402

from app.modules.admin.models import AppSettings  # noqa: E402
from app.modules.ai_admin import spend  # noqa: E402
from app.modules.ai_admin.models import ReferenceLetter  # noqa: E402
from app.modules.extraction.readers import read_upload  # noqa: E402


class SpendCapIn(BaseModel):
    enabled: bool
    monthly_usd: Decimal | None = Field(default=None, ge=0, le=1_000_000, decimal_places=2)


@router.get("/admin/spend-cap")
async def get_spend_cap(_: AdminUser, db: DbSession):
    enabled, cap = await spend.cap_settings(db)
    spent = await spend.month_spend(db)
    start, end = spend.month_bounds()
    return {"enabled": enabled, "monthly_usd": f"{cap:.2f}" if cap is not None else None,
            "spent_this_month_usd": f"{spent:.4f}", "month_starts": start, "resets_at": end}


@router.put("/admin/spend-cap")
async def set_spend_cap(body: SpendCapIn, admin: AdminUser, db: DbSession):
    if body.enabled and body.monthly_usd is None:
        raise ProblemError(422, "validation-error", "Some fields are invalid", errors=[
            {"field": "monthly_usd", "message": "Enter the monthly limit in USD."}])
    row = (await db.execute(select(AppSettings).where(AppSettings.id.is_(True)).with_for_update())).scalar_one_or_none()
    if row is None:
        row = AppSettings(id=True)
        db.add(row)
    row.spend_cap_enabled = body.enabled
    if body.monthly_usd is not None:
        row.spend_cap_usd = body.monthly_usd
    row.updated_by = admin.user.id
    await db.commit()
    return await get_spend_cap(admin, db)


@router.get("/admin/usage")
async def usage(_: AdminUser, db: DbSession, month: str | None = None):
    """AI usage and cost for a calendar month (UTC), e.g. ?month=2026-10."""
    target = None
    if month:
        try:
            target = _date.fromisoformat(f"{month}-01")
        except ValueError:
            raise ProblemError(422, "validation-error", "Some fields are invalid", errors=[
                {"field": "month", "message": "Use the format YYYY-MM."}])
    return await spend.usage_report(db, target)


# ---------------- reference letter library (Milestone 4) ----------------

REFERENCE_TYPES = ("docx", "pdf", "txt")
MAX_REFERENCE_BYTES = 10_000_000


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:30])


class ReferenceUpdate(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    is_active: bool | None = None


@router.get("/admin/reference-letters")
async def list_reference_letters(_: AdminUser, db: DbSession):
    rows = (await db.execute(
        select(ReferenceLetter, StoredFile).join(StoredFile, StoredFile.id == ReferenceLetter.file_id)
        .order_by(ReferenceLetter.id.desc())
    )).all()
    return {"items": [
        {"id": r.id, "label": r.label, "is_active": r.is_active, "file_id": f.id, "filename": f.original_filename,
         "characters": len((f.extracted or {}).get("text") or ""), "created_at": r.created_at}
        for r, f in rows
    ]}


@router.post("/admin/reference-letters", status_code=status.HTTP_201_CREATED)
async def upload_reference_letter(
    admin: AdminUser, db: DbSession, storage: StorageDep,
    file: Annotated[UploadFile, File()],
    label: Annotated[str, Form()] = "",
):
    """Add a reference demand letter. Only its format guides the AI, never its data."""
    name = file.filename or "reference"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in REFERENCE_TYPES:
        raise ProblemError(415, "unsupported-file-type", "Use a Word (.docx), PDF or TXT file")
    data = await file.read(MAX_REFERENCE_BYTES + 1)
    if len(data) > MAX_REFERENCE_BYTES:
        raise ProblemError(413, "file-too-large", "File too large", f'"{name}" is larger than 10.0 MB.')
    try:
        if ext == "pdf":
            read_upload(data, name, keep_images=False)  # validates (pages, password)
            text = _pdf_text(data)
        else:
            text = read_upload(data, name, keep_images=False).text or ""
    except UploadRejected as exc:
        raise ProblemError(exc.status, exc.slug, exc.title, exc.detail)
    except Exception:
        raise ProblemError(422, "file-unreadable", "The file could not be read")
    if len(text.strip()) < 50:
        raise ProblemError(422, "reference-no-text", "No readable text found",
                           "The reference letter needs selectable text (a scanned PDF can't be used as a format reference).")
    key = f"references/{uuid.uuid4().hex[:10]}-{name[-80:]}"
    try:
        await storage.write(key, data)
    except StorageError:
        raise ProblemError(503, "storage-unavailable", "File storage is unavailable")
    stored = StoredFile(kind="admin_reference", storage_key=key, original_filename=name,
                        mime_type={"pdf": "application/pdf", "txt": "text/plain"}.get(ext, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), uploaded_by=admin.user.id,
                        extracted={"text": text[:30_000]})
    db.add(stored)
    await db.flush()
    ref = ReferenceLetter(file_id=stored.id, label=(label.strip() or name)[:200], uploaded_by=admin.user.id)
    db.add(ref)
    await db.commit()
    return {"id": ref.id, "label": ref.label, "is_active": True, "file_id": stored.id, "filename": name,
            "characters": len(text[:30_000]), "created_at": ref.created_at}


@router.patch("/admin/reference-letters/{ref_id}")
async def update_reference_letter(ref_id: int, body: ReferenceUpdate, _: AdminUser, db: DbSession):
    ref = await db.get(ReferenceLetter, ref_id)
    if ref is None:
        raise ProblemError(404, "reference-not-found", "Reference letter not found")
    if body.label is not None:
        ref.label = body.label
    if body.is_active is not None:
        ref.is_active = body.is_active
    await db.commit()
    return {"id": ref.id, "label": ref.label, "is_active": ref.is_active}


@router.delete("/admin/reference-letters/{ref_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_letter(ref_id: int, _: AdminUser, db: DbSession, storage: StorageDep):
    ref = await db.get(ReferenceLetter, ref_id)
    if ref is None:
        raise ProblemError(404, "reference-not-found", "Reference letter not found")
    f = await db.get(StoredFile, ref.file_id)
    await db.delete(ref)
    if f is not None:
        await db.delete(f)
    await db.commit()
    if f is not None:
        try:
            await storage.delete_file(f.storage_key)
        except StorageError:
            pass  # row is gone; an orphaned file is harmless
    return Response(status_code=status.HTTP_204_NO_CONTENT)
