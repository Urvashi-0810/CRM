"""Letter .docx → PDF (LibreOffice) → PNG/JPG pages (pdfium), for Canva and Figma."""

import asyncio
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pypdfium2 as pdfium

from app.errors import ProblemError

CONVERT_TIMEOUT_SECONDS = 120
IMAGE_SCALE = 2  # 2 × 72 dpi = 144 dpi: sharp enough to design on, small enough to drag in
_WINDOWS_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
# LibreOffice is heavy; a couple of conversions at a time is plenty.
_slots = asyncio.Semaphore(2)


def find_soffice(configured: str | None) -> str | None:
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return next((p for p in _WINDOWS_PATHS if os.path.isfile(p)), None)


def _convert(soffice: str, docx: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="crm-pdf-") as tmp:
        work = Path(tmp)
        source = work / "letter.docx"
        source.write_bytes(docx)
        # A private profile per run: parallel runs don't fight over one profile lock.
        profile = (work / "profile").as_uri()
        try:
            result = subprocess.run(
                [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                 "--convert-to", "pdf", "--outdir", str(work), str(source)],
                capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ProblemError(504, "conversion-timeout", "Converting the letter took too long", "Try again in a moment.")
        pdf = work / "letter.pdf"
        if result.returncode != 0 or not pdf.is_file():
            raise ProblemError(502, "conversion-failed", "The letter could not be converted to PDF",
                               "Download the .docx instead, or try again.")
        return pdf.read_bytes()


async def docx_to_pdf(docx: bytes, soffice_setting: str | None) -> bytes:
    soffice = find_soffice(soffice_setting)
    if soffice is None:
        raise ProblemError(
            503, "converter-missing", "PDF conversion is not set up on the server",
            "LibreOffice must be installed on the server (see the setup guide). The .docx download still works.",
        )
    async with _slots:
        return await asyncio.to_thread(_convert, soffice, docx)


def _render(pdf: bytes, fmt: str) -> list[bytes]:
    doc = pdfium.PdfDocument(pdf)
    pages = []
    try:
        for page in doc:
            image = page.render(scale=IMAGE_SCALE).to_pil()
            out = io.BytesIO()
            if fmt == "jpg":
                image.convert("RGB").save(out, "JPEG", quality=92)
            else:
                image.save(out, "PNG", optimize=True)
            pages.append(out.getvalue())
    finally:
        doc.close()
    return pages


async def pdf_to_images(pdf: bytes, fmt: str) -> list[bytes]:
    """One image per page."""
    return await asyncio.to_thread(_render, pdf, fmt)


def zip_pages(pages: list[bytes], base_name: str, ext: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:  # images are already compressed
        for number, data in enumerate(pages, start=1):
            z.writestr(f"{base_name}_page-{number}.{ext}", data)
    return out.getvalue()
