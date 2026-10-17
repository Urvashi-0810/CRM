"""Errors in RFC 9457 "problem details" format (application/problem+json).

Every error the API returns has the same shape:
    {"type": "urn:crm:problem:<slug>", "title": "...", "status": 409, "detail": "..."}
plus, for validation errors, an "errors" list with one entry per invalid field.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemError(Exception):
    """Raise this from services/routers to return a problem+json response."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extensions = extensions


def problem_response(
    status: int,
    slug: str | None,
    title: str,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"urn:crm:problem:{slug}" if slug else "about:blank",
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    body.update(extensions)
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_MEDIA_TYPE)


async def _problem_error_handler(_: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(exc.status, exc.slug, exc.title, exc.detail, exc.headers, **exc.extensions)


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    try:
        title = HTTPStatus(exc.status_code).phrase
    except ValueError:
        title = "Error"
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != title else None
    return problem_response(exc.status_code, None, title, detail, getattr(exc, "headers", None))


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        errors.append({"field": ".".join(loc) or None, "message": err.get("msg", "Invalid value")})
    return problem_response(
        422,
        "validation-error",
        "Some fields are invalid",
        "Fix the listed fields and try again.",
        errors=errors,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
