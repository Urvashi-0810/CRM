"""Gemini adapter (google-genai SDK, generate_content).

Structured output uses response_mime_type="application/json" + response_json_schema.
PDFs and images are sent inline as bytes parts.
Gemini bills "thinking" tokens as output, so they are added to output_tokens.
"""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.modules.llm.base import Adapter, LlmError, LlmRequest, LlmResult


def to_contents(request: LlmRequest) -> list[types.Content]:
    contents: list[types.Content] = []
    for turn in request.turns:
        parts = []
        for p in turn.parts:
            if p.kind == "text":
                if (p.text or "").strip():
                    parts.append(types.Part.from_text(text=p.text))
            else:
                parts.append(types.Part.from_bytes(data=p.data, mime_type=p.mime))
        if not parts:
            continue
        role = "model" if turn.role == "assistant" else "user"
        if contents and contents[-1].role == role:
            contents[-1].parts.extend(parts)
        else:
            contents.append(types.Content(role=role, parts=parts))
    return contents


class GeminiAdapter(Adapter):
    provider = "gemini"

    def __init__(self, api_key: str, model: str, *, client: genai.Client | None = None,
                 timeout_ms: int = 300_000) -> None:
        self.model = model
        self.client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms)
        )

    async def generate(self, request: LlmRequest) -> LlmResult:
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            response_mime_type="application/json",
            response_json_schema=request.json_schema,
            max_output_tokens=request.max_output_tokens,
        )
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model, contents=to_contents(request), config=config
            )
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            message = getattr(exc, "message", None) or str(exc)
            if code == 429:
                raise LlmError("rate_limited", message) from exc
            if code in (401, 403):
                raise LlmError("auth", "The Gemini API key was rejected. Check it on the admin page.") from exc
            if code in (500, 503, 504):
                raise LlmError("overloaded", message) from exc
            if code == 400:
                raise LlmError("bad_request", message) from exc
            raise LlmError("error", message) from exc
        except Exception as exc:  # network errors
            raise LlmError("error", f"Could not reach Gemini: {exc}") from exc

        usage = response.usage_metadata
        prompt = (usage.prompt_token_count or 0) if usage else 0
        cached = (usage.cached_content_token_count or 0) if usage else 0
        output = ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        finish = None
        if response.candidates:
            finish = str(response.candidates[0].finish_reason) if response.candidates[0].finish_reason else None
        return LlmResult(
            text=response.text or "",
            input_tokens=max(prompt - cached, 0),
            output_tokens=output,
            cache_read_tokens=cached,
            request_id=getattr(response, "response_id", None),
            stop_reason=finish,
            raw_usage=usage.model_dump(exclude_none=True) if usage else {},
        )
