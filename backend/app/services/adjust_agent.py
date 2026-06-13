"""Claude-agent-service adjust provider — the gated LLM path (#14, ADR-0002).

The optional, **env-gated** :class:`AdjustProvider` that routes a conversational
adjust request through the in-cluster **claude-agent-service** instead of the
deterministic parser. It is OFF by default (``ADJUST_PROVIDER="deterministic"``);
set ``ADJUST_PROVIDER="claude-agent"`` (and supply ``CLAUDE_AGENT_TOKEN`` — the
Vault ``secret/claude-agent-service`` bearer) to enable it. So the feature ships
working with no external dependency and the LLM is a deliberate, reversible
upgrade — never a ship-dark requirement (ADR-0002).

The contract (ADR-0002, hard): the LLM **only proposes**. This provider asks the
model to map the user's free-text request to the *same small structured levers*
the deterministic provider uses — `volume_scale`, `exclude_equipment`,
`max_exercises` — as strict JSON, and parses that into an :class:`Adjustment`.
That proposal is then handed to :func:`app.services.adjust.validate_adjustment`
(clamped to Principle bounds) exactly like the deterministic one before anything
is applied. The model cannot prescribe a raw set/weight, cannot exceed the
levers, and cannot bypass validation — it can only suggest *which lever* and *how
far*, and even that is bounded by the engine.

Robustness: the call is timeout-guarded; on **any** failure (network, timeout,
non-JSON, junk fields) it **falls back to the deterministic provider** so the
gym-door request always returns a usable proposal. We use claude-agent-service's
OpenAI-compatible ``/v1/chat/completions`` (synchronous, low-latency) — the right
shape for a single-shot parse, versus the async ``/execute`` + poll path used for
long agent jobs.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.services.adjust import (
    Adjustment,
    AdjustProvider,
    DeterministicAdjustProvider,
)

log = logging.getLogger(__name__)

# The model is asked to emit ONLY this JSON object — the same levers the
# deterministic provider produces. Anything else is ignored / falls back.
_SYSTEM_PROMPT = (
    "You adjust a single gym workout to a user's request. You do NOT design "
    "workouts and you do NOT pick exercises, sets, reps, or weights. You only "
    "choose, from a fixed set of safe levers, how to nudge an already-generated "
    "workout. Respond with ONE JSON object and nothing else, with these optional "
    "keys:\n"
    '  "volume_scale": number in [0.5, 1.2] — multiply every set count (e.g. 0.7 '
    "to make it easier when the user is tired);\n"
    '  "exclude_equipment": array of equipment names to avoid today (only from '
    "the AVAILABLE list);\n"
    '  "max_exercises": integer >= 1 — cap the number of exercises (e.g. for a '
    "shorter session);\n"
    '  "note": short human explanation of what you changed.\n'
    "Omit a key if it does not apply. Never invent equipment not in AVAILABLE. "
    "Output JSON only — no prose, no code fences."
)


class ClaudeAgentAdjustProvider(AdjustProvider):
    """LLM adjust provider via claude-agent-service (gated; proposes only).

    Calls the OpenAI-compatible chat endpoint to map the request to the structured
    levers, parses strict JSON, and returns an :class:`Adjustment`. Falls back to
    the deterministic provider on any error so the path is never dark.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
        model: str = "sonnet",
        fallback: AdjustProvider | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.CLAUDE_AGENT_URL).rstrip("/")
        self._token = token if token is not None else settings.CLAUDE_AGENT_TOKEN
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.CLAUDE_AGENT_TIMEOUT_SECONDS
        )
        self._model = model
        self._fallback = fallback or DeterministicAdjustProvider()
        self._transport = transport

    def propose(self, request: str, *, equipment: list[str]) -> Adjustment:
        """Synchronous ABC entry point — not used in async routes.

        The async route calls :meth:`apropose`; this exists only to satisfy the
        ABC and defers to the deterministic fallback if ever called synchronously.
        """
        return self._fallback.propose(request, equipment=equipment)

    async def apropose(self, request: str, *, equipment: list[str]) -> Adjustment:
        """Propose via the LLM (async); fall back to deterministic on any failure."""
        if not self._token:
            log.warning("claude-agent adjust enabled but no token set; using fallback")
            return self._fallback.propose(request, equipment=equipment)
        try:
            content = await self._chat(request, equipment)
            parsed = self._parse(content, equipment)
            if parsed is not None:
                return parsed
            log.warning("claude-agent adjust returned unparseable content; fallback")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("claude-agent adjust call failed (%s); fallback", type(exc).__name__)
        return self._fallback.propose(request, equipment=equipment)

    async def _chat(self, request: str, equipment: list[str]) -> str:
        """One synchronous chat call; returns the assistant content (may be empty)."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"AVAILABLE equipment: {', '.join(equipment) or 'none'}.\n"
                        f"User request: {request}"
                    ),
                },
            ],
            "temperature": 0.0,
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"]).strip()

    def _parse(self, content: str, equipment: list[str]) -> Adjustment | None:
        """Parse the model's JSON into an :class:`Adjustment` (None if unusable).

        Tolerant of a stray code fence; strict about types. Equipment exclusions
        are intersected with what's AVAILABLE so the model can't invent one. The
        result is *not* clamped here — that's :func:`validate_adjustment`'s job
        (the engine's authority), kept the single place bounds live.
        """
        text = content.strip()
        if text.startswith("```"):
            # Strip a ```json … ``` fence if the model added one.
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None

        volume_scale = obj.get("volume_scale")
        if not isinstance(volume_scale, (int, float)):
            volume_scale = None
        else:
            volume_scale = float(volume_scale)

        available = {e.lower() for e in equipment}
        raw_excl = obj.get("exclude_equipment") or []
        exclude = (
            [e for e in raw_excl if isinstance(e, str) and e.lower() in available]
            if isinstance(raw_excl, list)
            else []
        )

        max_exercises = obj.get("max_exercises")
        if not isinstance(max_exercises, int) or isinstance(max_exercises, bool):
            max_exercises = None

        note = obj.get("note")
        note = note if isinstance(note, str) else ""

        adjustment = Adjustment(
            volume_scale=volume_scale,
            exclude_equipment=exclude,
            max_exercises=max_exercises,
            note=note or "Adjusted on your request.",
        )
        return adjustment


def get_adjust_provider() -> AdjustProvider:
    """Return the configured adjust provider (deterministic default; gated LLM).

    ``ADJUST_PROVIDER="claude-agent"`` selects the LLM provider; anything else
    (the default) selects the deterministic one. The single place the choice is
    made, so routes never branch on the env var.
    """
    if settings.ADJUST_PROVIDER == "claude-agent":
        return ClaudeAgentAdjustProvider()
    return DeterministicAdjustProvider()


async def propose_adjustment(
    provider: AdjustProvider, request: str, *, equipment: list[str]
) -> Adjustment:
    """Uniformly get a proposal from any provider, sync or async.

    The LLM provider exposes an async ``apropose`` (it does IO); the deterministic
    one is pure-sync. This dispatcher hides that from the route — it awaits
    ``apropose`` when present, else calls ``propose`` directly — so the endpoint
    stays provider-agnostic.
    """
    apropose = getattr(provider, "apropose", None)
    if apropose is not None:
        return await apropose(request, equipment=equipment)
    return provider.propose(request, equipment=equipment)
