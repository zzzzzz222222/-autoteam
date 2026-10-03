"""Validation-only LLM provider wrappers that count calls and enforce budgets.

Why a wrapper instead of a core change
--------------------------------------
``app/llm/provider.py`` does not record call counts, and the core must stay
frozen for v0.6.0.  ``execute_task`` and ``AgentRuntime`` accept any object with
``structured_completion(prompt, response_model)``, so counting and budgeting can
live entirely in the validation layer.

Two wrappers, on purpose
------------------------
* ``CountingProvider`` wraps a **real** provider (OpenAI / DeepSeek compatible).
* ``CountingMockProvider`` *subclasses* ``MockLLMProvider``.

The subclassing matters: ``AgentRuntime`` and ``execute_task`` branch on
``isinstance(provider, MockLLMProvider)`` to keep offline runs offline (forcing
``tool_mode="mock"``). A plain wrapper around the mock would silently flip the
engine into the *real* tool-calling branch, so the mock wrapper must preserve
that identity.

Budgets
-------
``CountingProvider`` enforces two independent limits, both **thread-safe**:

* ``max_calls`` — hard ceiling on real provider requests for the whole run.
* ``deadline`` — monotonic timestamp after which no new request is allowed
  (cooperative cancellation of the run).

A slot is *reserved* atomically before the request, so concurrent callers can
never exceed the ceiling. A blocked request raises ``LLMBudgetExceeded`` and is
recorded as **blocked** — never as a successful or failed call. Original
provider exceptions are always re-raised unchanged.

What is recorded
----------------
Per real call: index, start/finish (monotonic, same-run comparisons only),
duration, ok/failed, exception type, and a *redacted* short error string.
Per blocked call: index, reason (``max_llm_calls`` / ``run_deadline``) and the
run-relative offset. Never recorded: prompts, responses, keys, headers.

Token usage and API cost
------------------------
Token counts **are** observable. ``app/llm/provider.py`` copies ``response.usage``
into ``last_response_meta`` after each real call; this module reads it back via
``CountingProvider._inner_meta()`` and aggregates prompt / completion / total
tokens in ``summary()["token_usage"]``.

Cost is therefore derivable: ``validation/pricing.py`` multiplies the aggregated
tokens by the listed unit price for the model and reports
``estimated_cost_usd``. Both degrade honestly:

* ``token_usage`` is ``null`` when **no observed real call** carried a usage
  block (e.g. offline / mock runs) — never a fabricated estimate.
* ``estimated_cost_usd`` is ``null`` when the model has no row in
  ``validation/pricing.py`` — never guessed from a similar model.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from pydantic import BaseModel

from app.llm.provider import MockLLMProvider

from .sanitize import redact_text

TOKEN_USAGE_UNAVAILABLE_REASON = (
    "No observed real call in this run carried a response.usage block "
    "(offline/mock run, or the endpoint omitted usage), so token counts are "
    "reported as null rather than estimated. Token usage IS captured for real "
    "calls: app/llm/provider.py copies response.usage into last_response_meta "
    "and validation/counting_provider.py aggregates it."
)

BLOCK_REASON_MAX_CALLS = "max_llm_calls"
BLOCK_REASON_DEADLINE = "run_deadline"


class LLMBudgetExceeded(RuntimeError):
    """Raised when a provider request is refused by the run's budget.

    Deliberately *not* a ``ProviderError``: a budget refusal is a validation-layer
    decision, not a provider failure, and the two must stay distinguishable in
    the metrics and in agent error messages.
    """


class _CallLog:
    """Thread-safe per-call log + budget reservation shared by the wrappers."""

    def __init__(
        self,
        *,
        model: str,
        is_mock: bool,
        clock: Any = time.perf_counter,
        max_calls: int | None = None,
        deadline: float | None = None,
    ) -> None:
        self._clock = clock
        self._origin = clock()
        self._lock = threading.Lock()
        self._calls: list[dict[str, Any]] = []
        self._blocked: list[dict[str, Any]] = []
        self._reserved = 0
        self.model = model
        self.is_mock = is_mock
        self.max_calls = max_calls
        self.deadline = deadline

    # -- budget ------------------------------------------------------------
    def reserve(self) -> str | None:
        """Atomically reserve one real-call slot. Returns a block reason or None."""
        with self._lock:
            if self.deadline is not None and self._clock() > self.deadline:
                return BLOCK_REASON_DEADLINE
            if self.max_calls is not None and (len(self._calls) + self._reserved) >= self.max_calls:
                return BLOCK_REASON_MAX_CALLS
            self._reserved += 1
            return None

    def release(self) -> None:
        with self._lock:
            if self._reserved > 0:
                self._reserved -= 1

    def record_blocked(self, reason: str) -> None:
        with self._lock:
            self._blocked.append(
                {
                    "index": len(self._blocked) + 1,
                    "reason": reason,
                    "at_offset": round(self._clock() - self._origin, 6),
                }
            )

    # -- outcomes ----------------------------------------------------------
    def _entry(self, started: float, finished: float) -> dict[str, Any]:
        return {
            "index": len(self._calls) + 1,
            "started_at": round(started, 6),
            "finished_at": round(finished, 6),
            "started_offset": round(started - self._origin, 6),
            "duration": round(finished - started, 6),
        }

    @staticmethod
    def _meta_fields(meta: dict | None) -> dict:
        """Safe per-call metadata (finish_reason / token usage) when available."""
        if not meta:
            return {"finish_reason": "unavailable", "usage": None}
        return {
            "finish_reason": str(meta.get("finish_reason") or "unavailable"),
            "usage": meta.get("usage") if isinstance(meta.get("usage"), dict) else None,
        }

    def record_success(
        self, started: float, finished: float, meta: dict | None = None
    ) -> None:
        with self._lock:
            entry = self._entry(started, finished)
            entry.update({"ok": True, "error_type": "", "error": ""})
            entry.update(self._meta_fields(meta))
            self._calls.append(entry)

    def record_failure(
        self, started: float, finished: float, exc: BaseException, meta: dict | None = None
    ) -> None:
        with self._lock:
            entry = self._entry(started, finished)
            entry.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": redact_text(exc, limit=200),
                }
            )
            entry.update(self._meta_fields(meta))
            self._calls.append(entry)

    # -- reporting ---------------------------------------------------------
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    def blocked_count(self) -> int:
        with self._lock:
            return len(self._blocked)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            calls = list(self._calls)
            blocked = list(self._blocked)
        failures = [c for c in calls if not c["ok"]]
        durations = [c["duration"] for c in calls]
        finish_reasons: dict[str, int] = {}
        tokens_prompt = tokens_completion = tokens_total = 0
        tokens_available = False
        for call in calls:
            reason = str(call.get("finish_reason") or "unavailable")
            finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
            usage = call.get("usage")
            if isinstance(usage, dict):
                tokens_available = True
                tokens_prompt += int(usage.get("prompt_tokens") or 0)
                tokens_completion += int(usage.get("completion_tokens") or 0)
                tokens_total += int(usage.get("total_tokens") or 0)
        by_reason: dict[str, int] = {}
        for item in blocked:
            by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        return {
            "count": len(calls),
            "succeeded": len(calls) - len(failures),
            "failed": len(failures),
            "blocked": len(blocked),
            "blocked_by_reason": by_reason,
            "blocked_calls": blocked,
            "max_calls": self.max_calls,
            "model": self.model,
            "is_mock": self.is_mock,
            "total_duration": round(sum(durations), 6) if durations else 0.0,
            "max_duration": round(max(durations), 6) if durations else 0.0,
            "calls": calls,
            "clock": "time.perf_counter (monotonic; compare within one run only)",
            "finish_reasons": finish_reasons,
            "token_usage": (
                {
                    "prompt_tokens": tokens_prompt,
                    "completion_tokens": tokens_completion,
                    "total_tokens": tokens_total,
                }
                if tokens_available
                else None
            ),
            "token_usage_reason": (
                "" if tokens_available else TOKEN_USAGE_UNAVAILABLE_REASON
            ),
            "records_prompts_or_responses": False,
        }


class CountingProvider:
    """Wrap a real ``LLMProvider``; count, and enforce the run budget."""

    def __init__(
        self,
        inner: Any,
        *,
        model: str | None = None,
        max_calls: int | None = None,
        deadline: float | None = None,
    ) -> None:
        if not hasattr(inner, "structured_completion"):
            raise TypeError("CountingProvider requires a structured_completion provider")
        self.inner = inner
        self._log = _CallLog(
            model=model or getattr(inner, "model", "") or "",
            is_mock=isinstance(inner, MockLLMProvider),
            max_calls=max_calls,
            deadline=deadline,
        )

    # ``AgentRuntime`` inspects ``provider.model`` / ``isinstance(MockLLMProvider)``.
    @property
    def model(self) -> str:
        return self._log.model

    @property
    def is_mock(self) -> bool:
        return self._log.is_mock

    def set_deadline(self, deadline: float | None) -> None:
        """Cooperative cancellation point (monotonic seconds)."""
        self._log.deadline = deadline

    def _inner_meta(self) -> dict | None:
        meta = getattr(self.inner, "last_response_meta", None)
        return meta if isinstance(meta, dict) else None

    def structured_completion(
        self, prompt: str, response_model: type[BaseModel], *args: Any, **kwargs: Any
    ) -> BaseModel:
        block_reason = self._log.reserve()
        if block_reason is not None:
            self._log.record_blocked(block_reason)
            raise LLMBudgetExceeded(
                f"LLM call budget refused the request ({block_reason}); "
                f"spent={self._log.call_count()} blocked={self._log.blocked_count()}"
            )
        started = self._log._clock()
        try:
            result = self.inner.structured_completion(prompt, response_model, *args, **kwargs)
        except BaseException as exc:
            self._log.record_failure(started, self._log._clock(), exc, self._inner_meta())
            raise  # never swallow, never disguise a failure as success
        finally:
            self._log.release()
        self._log.record_success(started, self._log._clock(), self._inner_meta())
        return result

    def call_count(self) -> int:
        return self._log.call_count()

    def blocked_count(self) -> int:
        return self._log.blocked_count()

    def summary(self) -> dict[str, Any]:
        return self._log.summary()


class CountingMockProvider(MockLLMProvider):
    """Deterministic mock provider that also counts its calls.

    Stays a ``MockLLMProvider`` subclass so the engine's offline branch and
    ``tool_mode`` forcing are unchanged. No budget is applied: an offline run
    never touches the network, so there is nothing to protect.
    """

    def __init__(self, *, model: str = "mock") -> None:
        super().__init__(model=model)
        self._log = _CallLog(model=model, is_mock=True)
        self.inner = None

    @property
    def is_mock(self) -> bool:
        return True

    def structured_completion(
        self, prompt: str, response_model: type[BaseModel], *args: Any, **kwargs: Any
    ) -> BaseModel:
        started = self._log._clock()
        try:
            result = super().structured_completion(prompt, response_model)
        except BaseException as exc:
            self._log.record_failure(started, self._log._clock(), exc)
            raise
        self._log.record_success(started, self._log._clock())
        return result

    def call_count(self) -> int:
        return self._log.call_count()

    def blocked_count(self) -> int:
        return 0

    def summary(self) -> dict[str, Any]:
        return self._log.summary()
