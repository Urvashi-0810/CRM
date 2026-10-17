"""One place for every LLM call: picks the active provider, retries, logs tokens and cost."""

import asyncio
import random
import time
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.modules.ai_admin.models import LlmCall, LlmProviderConfig
from app.modules.llm.base import Adapter, LlmError, LlmRequest, LlmResult
from app.modules.llm.claude_adapter import ClaudeAdapter
from app.modules.llm.gemini_adapter import GeminiAdapter
from app.modules.llm.pricing import cost_usd
from app.modules.llm.secrets import decrypt_api_key
from app.modules.llm.test_adapter import TestAdapter

MAX_ATTEMPTS = 4
MAX_WAIT_SECONDS = 60

# provider -> factory(api_key, model). Tests replace entries to inject fakes.
ADAPTER_FACTORIES: dict[str, Callable[[str, str], Adapter]] = {
    "claude": lambda key, model: ClaudeAdapter(key, model),
    "gemini": lambda key, model: GeminiAdapter(key, model),
    "test": lambda key, model: TestAdapter(model),
}


class AiNotConfigured(Exception):
    pass


async def active_provider(db: AsyncSession, settings: Settings) -> LlmProviderConfig | None:
    config = (
        await db.execute(select(LlmProviderConfig).where(LlmProviderConfig.is_active))
    ).scalar_one_or_none()
    if config is None:
        return None
    if config.provider == "test" and not settings.llm_allow_test_provider:
        return None
    if config.provider != "test" and not config.api_key_encrypted:
        return None
    return config


def make_adapter(config: LlmProviderConfig, settings: Settings) -> Adapter:
    key = decrypt_api_key(settings, config.api_key_encrypted) if config.api_key_encrypted else ""
    return ADAPTER_FACTORIES[config.provider](key, config.model)


async def _log(
    sessionmaker: async_sessionmaker,
    *,
    provider: str,
    model: str,
    job_id: int | None,
    demand_id: int | None,
    outcome: str,
    result: LlmResult | None = None,
    error: str | None = None,
    request_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    # Own session + commit: the log must survive even if the job later fails.
    async with sessionmaker() as db:
        call = LlmCall(
            job_id=job_id, demand_id=demand_id, provider=provider, model=model,
            outcome=outcome, error=(error or "")[:2000] or None,
            provider_request_id=(result.request_id if result else request_id),
            duration_ms=duration_ms,
        )
        if result:
            call.input_tokens = result.input_tokens
            call.output_tokens = result.output_tokens
            call.cache_read_tokens = result.cache_read_tokens
            call.cache_write_tokens = result.cache_write_tokens
            call.cost_usd = cost_usd(
                provider, model,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                cache_read_tokens=result.cache_read_tokens, cache_write_tokens=result.cache_write_tokens,
            )
        db.add(call)
        await db.commit()


async def log_invalid_output(sessionmaker, *, provider, model, job_id, demand_id, error) -> None:
    await _log(sessionmaker, provider=provider, model=model, job_id=job_id, demand_id=demand_id,
               outcome="invalid_output", error=error)


async def call_llm(
    sessionmaker: async_sessionmaker,
    adapter: Adapter,
    request: LlmRequest,
    *,
    model: str,
    job_id: int | None,
    demand_id: int | None,
    sleep=asyncio.sleep,
) -> LlmResult:
    """Call the provider, retrying rate limits / overloads / network errors.

    Each attempt is logged to llm_calls. Raises LlmError after the last attempt.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            result = await adapter.generate(request)
        except LlmError as exc:
            outcome = exc.kind if exc.kind in ("rate_limited", "overloaded") else "error"
            await _log(sessionmaker, provider=adapter.provider, model=model, job_id=job_id,
                       demand_id=demand_id, outcome=outcome, error=str(exc),
                       request_id=exc.request_id,
                       duration_ms=int((time.monotonic() - started) * 1000))
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                raise
            wait = exc.retry_after if exc.retry_after is not None else min(2 ** attempt * 2, 30)
            await sleep(min(wait, MAX_WAIT_SECONDS) + random.uniform(0, 1))
            continue
        await _log(sessionmaker, provider=adapter.provider, model=model, job_id=job_id,
                   demand_id=demand_id, outcome="ok", result=result,
                   duration_ms=int((time.monotonic() - started) * 1000))
        return result
    raise LlmError("error", "unreachable")  # pragma: no cover
