"""Research tools and their registry (v0.2.0).

Two tools ship: ``web_search`` and ``mock_search``.

``web_search`` is offline-safe: without a configured search backend it returns
clearly-labeled offline results, so the whole research demo runs with no API key.
Wire a real backend by setting ``AUTOTEAM_WEB_SEARCH_URL`` + ``AUTOTEAM_WEB_SEARCH_API_KEY``.
``mock_search`` always returns deterministic stubs and is what the offline demo uses.

The runtime picks the tool via the registry ``mode`` ("auto" resolves to the
behavior-declared tool, "mock" forces the deterministic stub).
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    query: str
    results: list[str] = Field(default_factory=list)
    offline: bool = True


def mock_search(query: str) -> ToolResult:
    return ToolResult(
        query=query,
        offline=True,
        results=[
            f"[mock] Overview of '{query}' — market size and growth drivers.",
            f"[mock] Key players and positioning mentioned in '{query}' coverage.",
            f"[mock] Recent developments and signals related to '{query}'.",
        ],
    )


def calculator(query: str) -> ToolResult:
    return ToolResult(
        query=query,
        offline=True,
        results=[
            f"[calculator] deterministic sizing metrics computed for '{query}'.",
            "[calculator] offline stub — no live computation backend configured.",
        ],
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


def web_search(query: str) -> ToolResult:
    """Offline-safe web search: real backend if configured, else mock fallback."""
    api_key = os.getenv("AUTOTEAM_WEB_SEARCH_API_KEY")
    base_url = os.getenv("AUTOTEAM_WEB_SEARCH_URL")
    if api_key and base_url:
        try:
            import json as _json
            import urllib.parse
            import urllib.request

            url = f"{base_url}?q={urllib.parse.quote(query)}"
            request = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = _json.loads(response.read().decode())
                items = [str(item) for item in data.get("results", [])[:5]]
                if items:
                    return ToolResult(query=query, offline=False, results=items)
        except Exception:
            pass
    # Offline fallback (deterministic, explicitly labeled).
    result = mock_search(query)
    result.offline = True
    return result


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
        }

    def available(self) -> list[str]:
        return list(self._tools)

    def run(self, tool_name: str, query: str) -> ToolResult:
        if self.mode == "mock":
            impl = self._tools.get("mock_search")
        else:
            impl = self._tools.get(tool_name) or self._tools.get("mock_search")
        if impl is None:
            return ToolResult(query=query, results=[], offline=True)
        return impl(query)
