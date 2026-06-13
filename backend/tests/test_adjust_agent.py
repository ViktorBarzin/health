"""Gated claude-agent-service adjust provider (#14, ADR-0002).

Asserts the LLM path PROPOSES only and is never a hard dependency:

* a JSON proposal from the model is parsed into the structured levers;
* equipment the model invents (not AVAILABLE) is dropped;
* on ANY failure (HTTP error, timeout, non-JSON) it falls back to the
  deterministic provider — so the path is never dark;
* the provider factory defaults to deterministic and only switches on the env
  var.

No real network: a mock httpx transport returns canned chat responses.
"""

import httpx
import pytest

from app.services.adjust import Adjustment, DeterministicAdjustProvider
from app.services.adjust_agent import (
    ClaudeAgentAdjustProvider,
    get_adjust_provider,
    propose_adjustment,
)


def _transport(handler):
    return httpx.MockTransport(handler)


def _chat_response(content: str, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"detail": "boom"})
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
        },
    )


def _provider(handler, **kwargs) -> ClaudeAgentAdjustProvider:
    return ClaudeAgentAdjustProvider(
        base_url="http://agent.test",
        token="secret-token",
        timeout_seconds=5.0,
        transport=_transport(handler),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Parsing a model proposal
# --------------------------------------------------------------------------- #


async def test_parses_json_proposal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            '{"volume_scale": 0.7, "exclude_equipment": ["barbell"], '
            '"max_exercises": 3, "note": "Eased it back, no barbell, shorter."}'
        )

    provider = _provider(handler)
    adj = await provider.apropose("I'm tired, no barbell, keep it short", equipment=["barbell", "dumbbell"])
    assert adj.volume_scale == pytest.approx(0.7)
    assert adj.exclude_equipment == ["barbell"]
    assert adj.max_exercises == 3
    assert adj.note


async def test_strips_code_fence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response('```json\n{"volume_scale": 0.8}\n```')

    provider = _provider(handler)
    adj = await provider.apropose("easier", equipment=["dumbbell"])
    assert adj.volume_scale == pytest.approx(0.8)


async def test_drops_invented_equipment() -> None:
    # The model names equipment the user does NOT have → it's filtered out.
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response('{"exclude_equipment": ["barbell", "leg press machine"]}')

    provider = _provider(handler)
    adj = await provider.apropose("no barbell", equipment=["barbell", "dumbbell"])
    assert adj.exclude_equipment == ["barbell"]


async def test_sends_bearer_token_and_request() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["url"] = str(request.url)
        return _chat_response('{"volume_scale": 0.7}')

    provider = _provider(handler)
    await provider.apropose("tired", equipment=["dumbbell"])
    assert seen["auth"] == "Bearer secret-token"
    assert seen["url"].endswith("/v1/chat/completions")


# --------------------------------------------------------------------------- #
# Fallback on failure — never dark
# --------------------------------------------------------------------------- #


async def test_http_error_falls_back_to_deterministic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("", status=503)

    provider = _provider(handler)
    # "make it shorter" → the deterministic fallback caps exercises.
    adj = await provider.apropose("make it shorter", equipment=["barbell"])
    assert adj.max_exercises is not None  # came from the deterministic fallback


async def test_non_json_falls_back_to_deterministic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("sure, I'll make it shorter for you!")

    provider = _provider(handler)
    adj = await provider.apropose("make it shorter", equipment=["barbell"])
    assert adj.max_exercises is not None


async def test_no_token_falls_back() -> None:
    # Enabled but unconfigured (no token) → deterministic, no crash.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - not called
        raise AssertionError("should not call the agent without a token")

    provider = ClaudeAgentAdjustProvider(
        base_url="http://agent.test", token=None, transport=_transport(handler)
    )
    adj = await provider.apropose("I'm tired", equipment=["barbell"])
    assert adj.volume_scale is not None and adj.volume_scale < 1.0


async def test_connect_error_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    provider = _provider(handler)
    adj = await provider.apropose("no barbell", equipment=["barbell", "dumbbell"])
    assert "barbell" in adj.exclude_equipment  # deterministic fallback parsed it


# --------------------------------------------------------------------------- #
# Factory + dispatcher
# --------------------------------------------------------------------------- #


def test_factory_defaults_to_deterministic(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ADJUST_PROVIDER", "deterministic")
    assert isinstance(get_adjust_provider(), DeterministicAdjustProvider)


def test_factory_selects_agent_when_configured(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ADJUST_PROVIDER", "claude-agent")
    assert isinstance(get_adjust_provider(), ClaudeAgentAdjustProvider)


async def test_dispatcher_handles_sync_provider() -> None:
    # The deterministic provider has no apropose; the dispatcher still works.
    adj = await propose_adjustment(
        DeterministicAdjustProvider(), "make it shorter", equipment=["barbell"]
    )
    assert isinstance(adj, Adjustment)
    assert adj.max_exercises is not None
