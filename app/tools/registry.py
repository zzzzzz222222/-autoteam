"""Research tools and their registry.

v0.5.0: tools are now truly executable and structured.

- ``web_search`` — dual mode. Without ``AUTOTEAM_WEB_SEARCH_URL`` +
  ``AUTOTEAM_WEB_SEARCH_API_KEY`` it returns deterministic results clearly
  labeled ``offline_mock`` (never fake URLs). With both configured it performs
  a real HTTP call (timeout, structured errors, response validation; the key
  never appears in results or logs).
- ``calculator`` — safe AST-based arithmetic (``app.tools.calculator``), no eval.
- ``local_knowledge`` — controlled reads from the knowledge workspace
  (``app.tools.local_knowledge``).
- ``mock_search`` / ``data_analyzer`` / ``schema_validator`` / ``code_analysis``
  — deterministic offline stubs used by the offline demos.

Structured interface: ``validate(tool_name)`` raises ``ToolNotFound``;
``execute(tool_name, arguments)`` raises ``ToolValidationError`` /
``ToolExecutionError`` and otherwise returns a ``ToolResult``. The legacy
``run(tool_name, query)`` is kept unchanged for the v0.2-v0.4 paths.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from app.tools.calculator import safe_calculate
from app.tools.local_knowledge import search_knowledge


class SearchResult(BaseModel):
    title: str = ""
    url: str = ""  # empty is allowed for offline_mock sources — never faked
    snippet: str = ""
    source: str = "offline_mock"  # "web" | "offline_mock"


class SearchResults(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    offline: bool = True
    error: str | None = None


class ToolResult(BaseModel):
    query: str
    tool: str = ""
    results: list[str] = Field(default_factory=list)
    offline: bool = True
    # v0.6.0 honest execution nature (kept separate from ``offline`` which is
    # backward compatible): web | local | offline_mock | offline_fallback
    kind: str = "offline_mock"
    value: float | None = None  # calculator
    search_results: list[SearchResult] = Field(default_factory=list)
    error: str | None = None


class ToolError(Exception):
    """Base class for structured tool failures."""


class ToolNotFound(ToolError):
    pass


class ToolValidationError(ToolError):
    pass


class ToolExecutionError(ToolError):
    pass


class ToolNotAllowed(ToolError):
    """The tool exists but the calling agent is not authorised to use it.

    v0.6.11 (P610-2): ``Agent.tools`` is the permission boundary. This is raised
    *before* any execution so an unauthorised name can never cause an external
    call, a cost or a side effect. Distinct from ``ToolNotFound`` so an
    "unknown tool" and a "not allowed tool" stay separately auditable.
    """


def mock_search(query: str) -> ToolResult:
    stubs = _offline_web_results(query)
    return ToolResult(
        query=query,
        offline=True,
        results=[item.snippet for item in stubs],
        # Provenance: same shape as web_search offline fallback so Evidence
        # / Source collection works in mock mode (urls stay empty — never faked).
        search_results=stubs,
    )


def calculator(query: str) -> ToolResult:
    """``query`` is the arithmetic expression (e.g. ``(100 - 20) / 4``)."""
    outcome = safe_calculate(query)
    if outcome.error:
        return ToolResult(query=query, offline=True, kind="local", error=outcome.error)
    return ToolResult(
        query=query,
        offline=True,
        kind="local",
        value=outcome.value,
        results=[f"[calculator] {outcome.expression} = {outcome.value}"],
    )


def data_analyzer(query: str) -> ToolResult:
    return ToolResult(
        query=query,
        offline=True,
        results=[
            f"[data_analyzer] aggregated metric table derived for '{query}'.",
            f"[data_analyzer] trend summary extracted for '{query}'.",
            "[data_analyzer] offline stub — deterministic output, no live data.",
        ],
    )


def schema_validator(query: str) -> ToolResult:
    return ToolResult(
        query=query,
        offline=True,
        results=[
            f"[schema_validator] entity and relation checks executed for '{query}'.",
            "[schema_validator] offline stub — deterministic validation report.",
        ],
    )


def code_analysis(query: str) -> ToolResult:
    return ToolResult(
        query=query,
        offline=True,
        results=[
            f"[code_analysis] interface and module structure reviewed for '{query}'.",
            "[code_analysis] offline stub — deterministic findings, no execution.",
        ],
    )


def _offline_web_results(query: str) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"[offline_mock] overview of '{query}'",
            url="",
            snippet=f"offline deterministic stub about '{query}' — market size and growth drivers.",
            source="offline_mock",
        ),
        SearchResult(
            title=f"[offline_mock] key players for '{query}'",
            url="",
            snippet=f"offline deterministic stub about '{query}' — key players and positioning.",
            source="offline_mock",
        ),
        SearchResult(
            title=f"[offline_mock] recent signals for '{query}'",
            url="",
            snippet=f"offline deterministic stub about '{query}' — recent developments.",
            source="offline_mock",
        ),
    ]


def web_search(query: str) -> ToolResult:
    """Dual-mode web search.

    Offline (default): deterministic results, ``source_type=offline_mock``,
    empty URLs — real URLs are never fabricated. Real: one HTTPS POST against
    ``AUTOTEAM_WEB_SEARCH_URL`` (Tavily-compatible: JSON body ``{"query": ...}``
    with ``Authorization: Bearer``) using ``AUTOTEAM_WEB_SEARCH_API_KEY``; any
    failure (timeout, bad response, validation) degrades to the offline
    results plus a structured ``error`` — never a crash, never the API key.
    """
    api_key = os.getenv("AUTOTEAM_WEB_SEARCH_API_KEY")
    base_url = os.getenv("AUTOTEAM_WEB_SEARCH_URL")
    if api_key and base_url:
        try:
            import json as _json
            import urllib.request

            body = _json.dumps({"query": query}).encode("utf-8")
            request = urllib.request.Request(
                base_url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = _json.loads(response.read().decode())
            raw_items = data.get("results") if isinstance(data, dict) else None
            if not isinstance(raw_items, list):
                raise ValueError("response must contain a 'results' list")
            search_results: list[SearchResult] = []
            for item in raw_items[:5]:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    raise ValueError("each result must be an object with a 'url' string")
                search_results.append(
                    SearchResult(
                        title=str(item.get("title", "")),
                        url=item["url"],
                        # Tavily returns "content"; generic adapters use "snippet".
                        snippet=str(item.get("content") or item.get("snippet", "")),
                        source="web",
                    )
                )
            if not search_results:
                raise ValueError("empty search response")
            return ToolResult(
                query=query,
                offline=False,
                kind="web",
                results=[item.snippet for item in search_results],
                search_results=search_results,
            )
        except Exception as exc:
            fallback = _offline_web_results(query)
            return ToolResult(
                query=query,
                offline=True,
                kind="offline_fallback",
                results=[item.snippet for item in fallback],
                search_results=fallback,
                error=f"web search failed: {type(exc).__name__}",
            )
    offline = _offline_web_results(query)
    return ToolResult(
        query=query,
        offline=True,
        kind="offline_mock",
        results=[item.snippet for item in offline],
        search_results=offline,
    )


def local_knowledge(query: str) -> ToolResult:
    outcome = search_knowledge(query)
    if outcome.error and not outcome.matches:
        return ToolResult(query=query, offline=True, kind="local", results=[], error=outcome.error)
    results = [f"[knowledge:{match['file']}] {match['snippet']}" for match in outcome.matches]
    if not results:
        results = [f"[knowledge] no files matched '{query}' (offline workspace)"]
    return ToolResult(query=query, offline=True, kind="local", results=results)


# Required argument names per tool — used by ToolRegistry.execute validation.
REQUIRED_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "web_search": ("query",),
    "mock_search": ("query",),
    "calculator": ("expression",),
    "data_analyzer": ("query",),
    "schema_validator": ("query",),
    "code_analysis": ("query",),
    "local_knowledge": ("query",),
}


class ToolRegistry:
    def __init__(self, mode: str = "auto") -> None:
        self.mode = mode
        self._tools = {
            "web_search": web_search,
            "mock_search": mock_search,
            "calculator": calculator,
            "data_analyzer": data_analyzer,
            "schema_validator": schema_validator,
            "code_analysis": code_analysis,
            "local_knowledge": local_knowledge,
        }

    def available(self) -> list[str]:
        return list(self._tools)

    def available_for(self, allowed: object) -> list[str]:
        """Registered tools the caller is actually authorised to use (v0.6.11).

        Advertise only authorised tools to the LLM so the schema itself already
        reflects the permission boundary. ``allowed=None`` (an undeclared tool
        list) yields **no** tools — a missing declaration is never treated as
        "all tools".

        Order follows the *authorisation* list (v0.6.12) so the advertised schema
        is identical to ``AgentSpec.tools`` rather than merely the same set.
        """
        if allowed is None:
            return []
        if isinstance(allowed, str):
            allowed = [allowed]
        try:
            permitted = [str(name) for name in allowed]  # type: ignore[union-attr]
        except TypeError:
            return []
        seen: set[str] = set()
        return [
            name
            for name in permitted
            if name in self._tools and not (name in seen or seen.add(name))
        ]

    def validate_allowed(self, tool_name: str, allowed: object) -> None:
        """Second, code-level permission check (never rely on the LLM schema).

        Raises ``ToolNotFound`` for an unregistered tool and ``ToolNotAllowed``
        for a registered-but-unauthorised one. Both are raised *before*
        ``execute`` so nothing runs.
        """
        self.validate(tool_name)
        if allowed is None:
            raise ToolNotAllowed(f"tool '{tool_name}' denied: agent declares no tools")
        if isinstance(allowed, str):
            allowed = [allowed]
        try:
            permitted = {str(name) for name in allowed}  # type: ignore[union-attr]
        except TypeError:
            permitted = set()
        if tool_name not in permitted:
            raise ToolNotAllowed(
                f"tool '{tool_name}' denied: not in the agent's declared tools "
                f"{sorted(permitted)}"
            )

    def validate(self, tool_name: str) -> None:
        """Raise ``ToolNotFound`` if the tool is not registered."""
        if tool_name not in self._tools:
            raise ToolNotFound(f"tool '{tool_name}' is not registered")

    def execute(self, tool_name: str, arguments: dict[str, str]) -> ToolResult:
        """Structured execution: validate the tool and its arguments, then run.

        Argument problems raise ``ToolValidationError``; internal tool failures
        raise ``ToolExecutionError``. Both are caught by the agent runtime and
        converted into structured ``ToolResult``s.
        """
        self.validate(tool_name)
        required = REQUIRED_ARGUMENTS.get(tool_name, ("query",))
        for name in required:
            value = arguments.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ToolValidationError(
                    f"tool '{tool_name}' requires a non-empty '{name}' argument"
                )
        try:
            impl = self._tools[tool_name]
            if tool_name == "calculator":
                outcome = impl(arguments["expression"])
            else:
                outcome = impl(arguments["query"])
            outcome.tool = tool_name
            return outcome
        except ToolError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"tool '{tool_name}' failed: {type(exc).__name__}") from exc

    def run(self, tool_name: str, query: str) -> ToolResult:
        """Legacy entry point (v0.2-v0.4 paths). Never raises."""
        if self.mode == "mock":
            impl = self._tools.get("mock_search")
        else:
            impl = self._tools.get(tool_name) or self._tools.get("mock_search")
        if impl is None:
            return ToolResult(query=query, tool=tool_name, results=[], offline=True)
        try:
            if impl is calculator:
                result = calculator(query)
            else:
                result = impl(query)
            result.tool = tool_name
            return result
        except Exception as exc:
            return ToolResult(
                query=query, tool=tool_name, offline=True, error=f"{type(exc).__name__}: {exc}"
            )
