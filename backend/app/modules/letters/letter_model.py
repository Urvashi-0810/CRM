"""The letter model: what the AI returns and what code turns into a .docx and a preview.

The AI never writes the .docx itself. It returns blocks:

    {"title": "...", "blocks": [
        {"type": "heading",   "text": "...", "level": 1},
        {"type": "paragraph", "text": "..."},
        {"type": "bullets",   "items": ["...", "..."]},
        {"type": "table",     "columns": ["Position", "Qty"], "rows": [["Welder", "4"]]},
        {"type": "image",     "image_id": "img-12", "caption": "..."}
    ]}

Inline text may use **bold** and missing-information markers: [[MISSING: Employer]].
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MISSING_RE = re.compile(r"\[\[MISSING:\s*([^\]]+?)\s*\]\]")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


class Block(BaseModel):
    type: Literal["heading", "paragraph", "bullets", "table", "image"]
    text: str | None = None
    level: int | None = None
    items: list[str] | None = None
    columns: list[str] | None = None
    rows: list[list[str]] | None = None
    image_id: str | None = None
    caption: str | None = None

    @field_validator("level")
    @classmethod
    def clamp_level(cls, v: int | None) -> int | None:
        return None if v is None else min(max(v, 1), 3)


class Letter(BaseModel):
    title: str | None = None
    blocks: list[Block] = Field(default_factory=list)

    def normalised(self, known_image_ids: set[str]) -> "Letter":
        """Drop empty blocks and images the AI referenced but that don't exist; pad table rows."""
        out: list[Block] = []
        for b in self.blocks:
            if b.type in ("heading", "paragraph") and not (b.text or "").strip():
                continue
            if b.type == "bullets":
                items = [i for i in (b.items or []) if i and i.strip()]
                if not items:
                    continue
                b = b.model_copy(update={"items": items})
            if b.type == "table":
                columns = b.columns or []
                rows = [r for r in (b.rows or []) if any((c or "").strip() for c in r)]
                if not columns and not rows:
                    continue
                width = max([len(columns)] + [len(r) for r in rows])
                columns = (columns + [""] * width)[:width]
                rows = [(r + [""] * width)[:width] for r in rows]
                b = b.model_copy(update={"columns": columns, "rows": rows})
            if b.type == "image" and b.image_id not in known_image_ids:
                continue
            out.append(b)
        return self.model_copy(update={"blocks": out})

    def missing_markers(self) -> list[str]:
        found: list[str] = []
        texts: list[str] = [self.title or ""]
        for b in self.blocks:
            texts += [b.text or "", b.caption or ""] + (b.items or []) + (b.columns or [])
            texts += [c for row in (b.rows or []) for c in row]
        for t in texts:
            for m in MISSING_RE.findall(t):
                if m not in found:
                    found.append(m)
        return found


# JSON schema handed to the AI providers (structured output). Kept flat and simple so it
# works with both Claude and Gemini: no recursion, no numeric/string length constraints,
# nullable fields instead of optional ones.
def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}

BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["heading", "paragraph", "bullets", "table", "image"]},
        "text": _nullable(_STR),
        "level": _nullable({"type": "integer"}),
        "items": _nullable(_STR_LIST),
        "columns": _nullable(_STR_LIST),
        "rows": _nullable({"type": "array", "items": _STR_LIST}),
        "image_id": _nullable(_STR),
        "caption": _nullable(_STR),
    },
    "required": ["type", "text", "level", "items", "columns", "rows", "image_id", "caption"],
    "additionalProperties": False,
}

TRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "project": _nullable(_STR),
        "trade": _STR,
        "quantity": {"type": "integer"},
    },
    "required": ["project", "trade", "quantity"],
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["ask", "letter", "answer", "refuse"]},
        "message": _STR,
        "questions": _STR_LIST,
        "missing_fields": _STR_LIST,
        "letter": _nullable({
            "type": "object",
            "properties": {
                "title": _nullable(_STR),
                "blocks": {"type": "array", "items": BLOCK_SCHEMA},
            },
            "required": ["title", "blocks"],
            "additionalProperties": False,
        }),
        "extracted": _nullable({
            "type": "object",
            "properties": {
                "country": _nullable(_STR),
                "employer": _nullable(_STR),
                "vacancy": _nullable({"type": "integer"}),
                "trades": {"type": "array", "items": TRADE_SCHEMA},
            },
            "required": ["country", "employer", "vacancy", "trades"],
            "additionalProperties": False,
        }),
    },
    "required": ["action", "message", "questions", "missing_fields", "letter", "extracted"],
    "additionalProperties": False,
}


class ExtractedTrade(BaseModel):
    project: str | None = None
    trade: str
    quantity: int


class Extracted(BaseModel):
    country: str | None = None
    employer: str | None = None
    vacancy: int | None = None
    trades: list[ExtractedTrade] = Field(default_factory=list)


class AiResponse(BaseModel):
    action: Literal["ask", "letter", "answer", "refuse"]
    message: str = ""
    questions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    letter: Letter | None = None
    extracted: Extracted | None = None
