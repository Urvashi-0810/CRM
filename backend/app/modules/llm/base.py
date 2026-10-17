"""Provider-neutral request/response types for the LLM gateway."""

from dataclasses import dataclass, field


@dataclass
class Part:
    """One piece of a message: text, an image, or a PDF document."""

    kind: str  # "text" | "image" | "pdf"
    text: str | None = None
    data: bytes | None = None
    mime: str | None = None


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    parts: list[Part]


@dataclass
class LlmRequest:
    system: str
    turns: list[Turn]
    json_schema: dict
    max_output_tokens: int = 16_000


@dataclass
class LlmResult:
    text: str
    input_tokens: int = 0          # uncached input
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_id: str | None = None
    stop_reason: str | None = None
    raw_usage: dict = field(default_factory=dict)


class LlmError(Exception):
    """A provider call failed.

    kind: rate_limited | overloaded | auth | bad_request | error
    retry_after: seconds to wait before retrying (if the provider said so)
    """

    def __init__(self, kind: str, message: str, retry_after: float | None = None,
                 request_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after
        self.request_id = request_id

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limited", "overloaded", "error")


class Adapter:
    provider: str

    async def generate(self, request: LlmRequest) -> LlmResult:  # pragma: no cover
        raise NotImplementedError
