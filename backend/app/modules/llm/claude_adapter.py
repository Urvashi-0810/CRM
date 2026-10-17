"""Claude (Anthropic Messages API) adapter.

Structured output uses output_config.format = json_schema
(https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
PDFs are sent as base64 "document" blocks and images as base64 "image" blocks.
The system prompt is marked for prompt caching, so repeated calls in a chat re-use it.
"""

import base64

import anthropic

from app.modules.llm.base import Adapter, LlmError, LlmRequest, LlmResult


def _block(part) -> dict:
    if part.kind == "text":
        return {"type": "text", "text": part.text or ""}
    data = base64.standard_b64encode(part.data or b"").decode()
    if part.kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    return {"type": "image", "source": {"type": "base64", "media_type": part.mime, "data": data}}


def to_messages(request: LlmRequest) -> list[dict]:
    messages: list[dict] = []
    for turn in request.turns:
        content = [_block(p) for p in turn.parts if p.kind != "text" or (p.text or "").strip()]
        if not content:
            continue
        if messages and messages[-1]["role"] == turn.role:
            messages[-1]["content"].extend(content)  # the API needs alternating roles
        else:
            messages.append({"role": turn.role, "content": content})
    # Cache everything up to the last user turn (inputs + history), so follow-up
    # messages in the same chat pay the cheap cached rate for the attachments.
    if messages:
        last = messages[-1]["content"][-1]
        last["cache_control"] = {"type": "ephemeral"}
    return messages


class ClaudeAdapter(Adapter):
    provider = "claude"

    def __init__(self, api_key: str, model: str, *, client: anthropic.AsyncAnthropic | None = None,
                 timeout: float = 300.0) -> None:
        self.model = model
        # Retries are done by the gateway (so each attempt is logged), not by the SDK.
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout)

    async def generate(self, request: LlmRequest) -> LlmResult:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=request.max_output_tokens,
                system=[{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
                messages=to_messages(request),
                output_config={"format": {"type": "json_schema", "schema": request.json_schema}},
            )
        except anthropic.RateLimitError as exc:
            raise LlmError("rate_limited", _message(exc), _retry_after(exc), _request_id(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise LlmError("auth", "The Claude API key was rejected. Check it on the admin page.",
                           request_id=_request_id(exc)) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LlmError("auth", _message(exc), request_id=_request_id(exc)) from exc
        except anthropic.BadRequestError as exc:
            raise LlmError("bad_request", _message(exc), request_id=_request_id(exc)) from exc
        except anthropic.APIStatusError as exc:
            kind = "overloaded" if exc.status_code in (503, 529) else "error"
            raise LlmError(kind, _message(exc), _retry_after(exc), _request_id(exc)) from exc
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            raise LlmError("error", f"Could not reach Claude: {exc}") from exc

        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        usage = response.usage
        return LlmResult(
            text=text,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            request_id=getattr(response, "_request_id", None),
            stop_reason=response.stop_reason,
            raw_usage=usage.model_dump() if hasattr(usage, "model_dump") else {},
        )


def _message(exc: anthropic.APIStatusError) -> str:
    try:
        return exc.body["error"]["message"]  # type: ignore[index]
    except Exception:
        return str(exc)


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after"))
    except (TypeError, ValueError, AttributeError):
        return None


def _request_id(exc: anthropic.APIStatusError) -> str | None:
    return getattr(exc, "request_id", None)
