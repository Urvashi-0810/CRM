"""Read uploaded files into something the AI can use.

- Word (.docx): text and tables in document order; pictures inside it.
- Excel (.xlsx) / CSV / TXT: every sheet as a table of rows; pictures inside it.
- PDF: sent to the AI as the PDF itself (both Claude and Gemini read PDFs, including scans).
- Images (PNG, JPG, WEBP, GIF): sent to the AI as images.

Old binary formats (.doc, .xls) are refused with a clear "save as" message.
Every limit breach raises UploadRejected with a message for the user.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field

from docx import Document
from docx.oxml.ns import qn
from openpyxl import load_workbook
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
PIL_TO_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}

MAX_IMAGE_SIDE = 8000          # Claude's maximum image dimensions
MAX_PDF_PAGES = 100            # Claude: 100 pages when the context window is under 1M tokens
MAX_TEXT_CHARS = 200_000       # extracted text per file
MAX_SHEET_ROWS = 2_000
MIN_EMBEDDED_IMAGE_SIDE = 64   # smaller pictures are icons/bullets, not worth showing the AI


class UploadRejected(Exception):
    def __init__(self, status: int, slug: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.slug, self.title, self.detail = status, slug, title, detail


@dataclass
class EmbeddedImage:
    data: bytes
    mime: str
    width: int
    height: int
    name: str


@dataclass
class ReadResult:
    """What a file contributes to the AI conversation."""

    mode: str                      # "text" | "pdf" | "image"
    mime: str
    text: str | None = None        # for mode "text"
    pages: int | None = None       # for mode "pdf"
    width: int | None = None       # for mode "image"
    height: int | None = None
    images: list[EmbeddedImage] = field(default_factory=list)  # pictures found inside


def _too_large(detail: str) -> UploadRejected:
    return UploadRejected(413, "file-too-large", "File too large", detail)


def _unsupported(detail: str) -> UploadRejected:
    return UploadRejected(415, "unsupported-file-type", "This file type is not supported", detail)


def _unreadable(name: str) -> UploadRejected:
    return UploadRejected(
        422, "file-unreadable", "The file could not be read",
        f'"{name}" seems damaged or is not what its name says. Open and re-save it, then try again.',
    )


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _image_info(data: bytes, name: str) -> tuple[str, int, int]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (w, h) = img.format, img.size
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise _unreadable(name)
    if fmt not in PIL_TO_MIME:
        raise _unsupported(f'"{name}" is a {fmt} image. Use PNG, JPG, WEBP or GIF.')
    return PIL_TO_MIME[fmt], w, h


def _table_text(rows: list[list[str]]) -> str:
    lines = []
    for row in rows:
        cells = [c.replace("\n", " ").replace("|", "/").strip() for c in row]
        if any(cells):
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _clean_cells(cells: list[str]) -> list[str]:
    # Merged cells repeat their text in python-docx; keep one copy.
    out: list[str] = []
    for c in cells:
        if not out or c != out[-1]:
            out.append(c)
    return out


def _check_text(text: str, name: str) -> str:
    if len(text) > MAX_TEXT_CHARS:
        raise _too_large(
            f'"{name}" contains too much text ({len(text):,} characters; the limit is '
            f"{MAX_TEXT_CHARS:,}). Remove what isn't needed or split it into smaller files."
        )
    return text


def _collect_images(blobs: list[tuple[bytes, str]]) -> list[EmbeddedImage]:
    images: list[EmbeddedImage] = []
    for data, name in blobs:
        try:
            with Image.open(io.BytesIO(data)) as img:
                fmt, (w, h) = img.format, img.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            continue  # e.g. EMF/WMF drawings the AI can't read
        if fmt not in PIL_TO_MIME or min(w, h) < MIN_EMBEDDED_IMAGE_SIDE or max(w, h) > MAX_IMAGE_SIDE:
            continue
        images.append(EmbeddedImage(data, PIL_TO_MIME[fmt], w, h, name))
    return images


def read_docx(data: bytes, name: str, *, keep_images: bool) -> ReadResult:
    try:
        doc = Document(io.BytesIO(data))
    except Exception:
        raise _unreadable(name)
    parts: list[str] = []
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            text = "".join(t.text or "" for t in child.iter(qn("w:t"))).strip()
            if text:
                parts.append(text)
        elif child.tag == qn("w:tbl"):
            rows = []
            for tr in child.iter(qn("w:tr")):
                cells = []
                for tc in tr.iter(qn("w:tc")):
                    cells.append(" ".join(
                        "".join(t.text or "" for t in p.iter(qn("w:t"))).strip()
                        for p in tc.iter(qn("w:p"))
                    ).strip())
                rows.append(_clean_cells(cells))
            table = _table_text(rows)
            if table:
                parts.append(table)
    text = _check_text("\n\n".join(parts), name)

    images: list[EmbeddedImage] = []
    if keep_images:
        blobs = [
            (rel.target_part.blob, rel.target_ref.rsplit("/", 1)[-1])
            for rel in doc.part.rels.values()
            if "image" in rel.reltype and not rel.is_external
        ]
        images = _collect_images(blobs)
    return ReadResult(mode="text", mime="text/plain", text=text, images=images)


def read_xlsx(data: bytes, name: str, *, keep_images: bool) -> ReadResult:
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        raise _unreadable(name)
    parts: list[str] = []
    blobs: list[tuple[bytes, str]] = []
    for ws in wb.worksheets:
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= MAX_SHEET_ROWS:
                raise _too_large(
                    f'Sheet "{ws.title}" in "{name}" has more than {MAX_SHEET_ROWS:,} rows. '
                    "Remove rows that aren't part of the requirement."
                )
            rows.append(["" if v is None else str(v).replace("\xa0", " ").strip() for v in row])
        table = _table_text(rows)
        if table:
            parts.append(f"Sheet: {ws.title}\n{table}")
        if keep_images:
            for img in getattr(ws, "_images", []):
                try:
                    blobs.append((img._data(), f"{ws.title}-image"))
                except Exception:
                    continue
    text = _check_text("\n\n".join(parts), name)
    return ReadResult(
        mode="text", mime="text/plain", text=text,
        images=_collect_images(blobs) if keep_images else [],
    )


def read_csv_or_txt(data: bytes, name: str, ext: str) -> ReadResult:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            raw = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise _unreadable(name)
    if ext == "csv":
        rows = list(csv.reader(io.StringIO(raw)))
        if len(rows) > MAX_SHEET_ROWS:
            raise _too_large(f'"{name}" has more than {MAX_SHEET_ROWS:,} rows.')
        raw = _table_text(rows)
    return ReadResult(mode="text", mime="text/plain", text=_check_text(raw, name))


def read_pdf(data: bytes, name: str) -> ReadResult:
    if not data.startswith(b"%PDF"):
        raise _unreadable(name)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadRejected(
                422, "pdf-encrypted", "The PDF is password-protected",
                f'Remove the password from "{name}" and upload it again.',
            )
        pages = len(reader.pages)
    except UploadRejected:
        raise
    except (PdfReadError, Exception):
        raise _unreadable(name)
    if pages > MAX_PDF_PAGES:
        raise _too_large(
            f'"{name}" has {pages} pages; the limit is {MAX_PDF_PAGES}. Upload only the pages you need.'
        )
    return ReadResult(mode="pdf", mime="application/pdf", pages=pages)


def read_image(data: bytes, name: str) -> ReadResult:
    mime, w, h = _image_info(data, name)
    if max(w, h) > MAX_IMAGE_SIDE:
        raise _too_large(
            f'"{name}" is {w}×{h} pixels; the limit is {MAX_IMAGE_SIDE} pixels on each side.'
        )
    return ReadResult(mode="image", mime=mime, width=w, height=h)


def read_upload(data: bytes, filename: str, *, keep_images: bool) -> ReadResult:
    """Validate and read one uploaded file. Raises UploadRejected with a user message."""
    ext = extension_of(filename)
    if ext in ("doc", "xls", "ppt", "pptx"):
        new = {"doc": ".docx", "xls": ".xlsx"}.get(ext)
        hint = f" Open it and save it as {new}." if new else ""
        raise _unsupported(f'"{filename}" is an old or unsupported format.{hint}')
    if ext == "docx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise _unreadable(filename)
        return read_docx(data, filename, keep_images=keep_images)
    if ext in ("xlsx", "xlsm"):
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise _unreadable(filename)
        return read_xlsx(data, filename, keep_images=keep_images)
    if ext in ("csv", "txt"):
        return read_csv_or_txt(data, filename, ext)
    if ext == "pdf":
        return read_pdf(data, filename)
    if ext in IMAGE_TYPES:
        return read_image(data, filename)
    raise _unsupported(
        f'"{filename}" can\'t be used. Supported: Word (.docx), Excel (.xlsx), CSV, TXT, PDF, '
        "and images (PNG, JPG, WEBP, GIF)."
    )
