"""Check the exact requests sent to Claude and Gemini, and how replies/errors are read.

These use the real SDKs with a fake HTTP transport (no network, no API key needed).
"""

import base64
import json

import anthropic
import httpx
import httpx2
import pytest
from google import genai
from google.genai import types

from app.modules.letters.letter_model import RESPONSE_SCHEMA
from app.modules.llm.base import LlmError, LlmRequest, Part, Turn
from app.modules.llm.claude_adapter import ClaudeAdapter
from app.modules.llm.gemini_adapter import GeminiAdapter

REPLY = {"action": "answer", "message": "Qatar", "questions": [], "missing_fields": [],
         "letter": None, "extracted": None}


def _request():
    return LlmRequest(
        system="SYSTEM RULES",
        turns=[
            Turn("user", [Part("text", text="=== Attachment F1 ==="), Part("pdf", data=b"%PDF-1.4", mime="application/pdf"),
                          Part("image", data=b"\x89PNG", mime="image/png"), Part("text", text="Which country?")]),
            Turn("assistant", [Part("text", text="Earlier answer")]),
            Turn("user", [Part("text", text="Thanks")]),
        ],
        json_schema=RESPONSE_SCHEMA,
    )


async def test_claude_request_shape_and_usage():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx2.Response(200, headers={"request-id": "req_1"}, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": json.dumps(REPLY)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 30,
                      "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 50},
        })

    client = anthropic.AsyncAnthropic(api_key="sk-test", max_retries=0,
                                      http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    result = await ClaudeAdapter("sk-test", "claude-sonnet-5-5", client=client).generate(_request())

    body = seen["body"]
    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert body["model"] == "claude-sonnet-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"][0]["text"] == "SYSTEM RULES" and body["system"][0]["cache_control"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    first = body["messages"][0]["content"]
    assert first[1] == {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                      "data": base64.b64encode(b"%PDF-1.4").decode()}}
    assert first[2]["type"] == "image" and first[2]["source"]["media_type"] == "image/png"
    assert body["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert json.loads(result.text)["message"] == "Qatar"
    assert (result.input_tokens, result.output_tokens, result.cache_read_tokens, result.cache_write_tokens) == (120, 30, 1000, 50)


@pytest.mark.parametrize("status,kind", [(429, "rate_limited"), (529, "overloaded"), (401, "auth"), (400, "bad_request")])
async def test_claude_errors_mapped(status, kind):
    def handler(request):
        return httpx2.Response(status, headers={"retry-after": "7"},
                              json={"type": "error", "error": {"type": "x", "message": "nope"}})

    client = anthropic.AsyncAnthropic(api_key="k", max_retries=0,
                                      http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    with pytest.raises(LlmError) as exc:
        await ClaudeAdapter("k", "claude-sonnet-5-5", client=client).generate(_request())
    assert exc.value.kind == kind
    if kind == "rate_limited":
        assert exc.value.retry_after == 7.0


async def test_gemini_request_shape_and_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(REPLY)}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 1500, "cachedContentTokenCount": 1000,
                              "candidatesTokenCount": 40, "thoughtsTokenCount": 60},
            "responseId": "resp_1",
        })

    client = genai.Client(api_key="g-key", http_options=types.HttpOptions(
        async_client_args={"transport": httpx.MockTransport(handler)}))
    result = await GeminiAdapter("g-key", "gemini-3.8-flash", client=client).generate(_request())

    body = seen["body"]
    assert "gemini-3.8-flash:generateContent" in seen["url"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYSTEM RULES"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in body["generationConfig"]
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    inline = [p["inlineData"].get("mimeType") or p["inlineData"].get("mime_type")
              for p in body["contents"][0]["parts"] if "inlineData" in p]
    assert inline == ["application/pdf", "image/png"]
    assert json.loads(result.text)["action"] == "answer"
    assert (result.input_tokens, result.cache_read_tokens, result.output_tokens) == (500, 1000, 100)
