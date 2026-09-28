"""Dependency-free rendering helpers: DAG as SVG, execution as an HTML timeline.

The UI deliberately avoids Graphviz, Plotly and any front-end build step, so both
the topology graph and the execution timeline are produced as plain markup.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.models.topology import Topology
from app.scheduler.models import ExecutionStatus
from app.topology.validator import TopologyValidator, compute_parallel_layers

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.demo.service import ExecutionRun

NODE_WIDTH = 150
NODE_HEIGHT = 38
HORIZONTAL_GAP = 22
VERTICAL_GAP = 44
MARGIN = 14

STATUS_COLORS: Mapping[str, str] = {
    ExecutionStatus.SUCCESS.value: "#16A34A",
    ExecutionStatus.FAILED.value: "#DC2626",
    ExecutionStatus.SKIPPED.value: "#9CA3AF",
    ExecutionStatus.RUNNING.value: "#2563EB",
    ExecutionStatus.READY.value: "#6366F1",
    ExecutionStatus.PENDING.value: "#CBD5E1",
}

_EDGE_COLOR = "#94A3B8"
_TEXT_COLOR = "#111827"

_TIMELINE_CSS = (
    "<style>"
    ".row{display:flex;align-items:center;gap:10px;height:28px;"
    "font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px;color:#374151}"
    ".name{width:150px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
    ".track{position:relative;flex:1;height:10px;background:#F1F3F7;border-radius:999px}"
    ".bar{position:absolute;top:0;height:10px;border-radius:999px;min-width:2px}"
    ".value{width:150px;flex:none;text-align:right;color:#6B7280;font-variant-numeric:tabular-nums}"
    "</style>"
)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int = 18) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def layout_positions(topology: Topology) -> tuple[dict[str, tuple[float, float]], float, float]:
    """Layered layout: one row per parallel layer, each row horizontally centred."""
    layers = topology.parallel_layers
    if not layers:
        layers = compute_parallel_layers(TopologyValidator().build_graph(topology))
    columns = max((len(layer) for layer in layers), default=1)
    rows = len(layers)
    content_width = columns * NODE_WIDTH + max(columns - 1, 0) * HORIZONTAL_GAP
    content_height = rows * NODE_HEIGHT + max(rows - 1, 0) * VERTICAL_GAP
    positions: dict[str, tuple[float, float]] = {}
    for row, layer in enumerate(layers):
        row_width = len(layer) * NODE_WIDTH + max(len(layer) - 1, 0) * HORIZONTAL_GAP
        offset_x = (content_width - row_width) / 2
        for column, agent_id in enumerate(layer):
            positions[agent_id] = (
                MARGIN + offset_x + column * (NODE_WIDTH + HORIZONTAL_GAP),
                MARGIN + row * (NODE_HEIGHT + VERTICAL_GAP),
            )
    return positions, content_width + 2 * MARGIN, content_height + 2 * MARGIN


def render_topology_svg(topology: Topology, labels: Mapping[str, str]) -> str:
    """Render a validated topology as a self-contained SVG string."""
    positions, width, height = layout_positions(topology)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="100%" height="{height:.0f}" role="img" aria-label="{topology.type.value} DAG">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        f'fill="{_EDGE_COLOR}"/></marker></defs>',
    ]
    for edge in topology.edges:
        source_x, source_y = positions[edge.source]
        target_x, target_y = positions[edge.target]
        x1 = source_x + NODE_WIDTH / 2
        y1 = source_y + NODE_HEIGHT
        x2 = target_x + NODE_WIDTH / 2
        y2 = target_y - 2
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{_EDGE_COLOR}" '
            'stroke-width="1.6" marker-end="url(#arrow)"/>'
        )
    for agent_id, (x, y) in positions.items():
        is_root = agent_id == topology.root_agent
        fill = "#EEF2FF" if is_root else "#FFFFFF"
        stroke = "#6366F1" if is_root else "#CBD5E1"
        label = _escape(_truncate(labels.get(agent_id, agent_id)))
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
        )
        parts.append(
            f'<text x="{x + NODE_WIDTH / 2:.1f}" y="{y + NODE_HEIGHT / 2:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle" font-size="12.5" '
            f'font-family="ui-sans-serif, system-ui, sans-serif" '
            f'fill="{_TEXT_COLOR}">{label}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_topology_text(topology: Topology, labels: Mapping[str, str]) -> str:
    """Terminal-friendly fallback: one line per parallel layer."""
    layers = topology.parallel_layers or compute_parallel_layers(
        TopologyValidator().build_graph(topology)
    )
    return "\n".join(
        "  |  ".join(_truncate(labels.get(agent_id, agent_id), 24) for agent_id in layer)
        for layer in layers
    )


def render_timeline_html(run: "ExecutionRun", labels: Mapping[str, str] | None = None) -> str:
    """Render per-agent start/duration as a minimal Gantt-style bar chart."""
    names = labels or {}
    total = max(run.duration, 1e-6)
    rows: list[str] = []
    for agent_id in run.topology.agents:
        result = run.results.get(agent_id)
        status = result.status.value if result else ExecutionStatus.PENDING.value
        color = STATUS_COLORS.get(status, "#CBD5E1")
        if result is not None and result.started_at is not None:
            offset = max(result.started_at - run.started_at, 0.0)
            span = max(result.duration or 0.0, total * 0.012)
        else:
            offset = total
            span = total * 0.012
        left = min(offset / total * 100.0, 100.0)
        bar_width = max(span / total * 100.0, 1.2)
        duration_text = f"{result.duration:.3f}s" if result is not None and result.duration else "—"
        rows.append(
            '<div class="row"><div class="name">'
            + _escape(_truncate(names.get(agent_id, agent_id), 22))
            + '</div><div class="track"><div class="bar" style="left:'
            + f"{left:.2f}%;width:{bar_width:.2f}%;background:{color}"
            + '"></div></div><div class="value">'
            + f"{status.upper()} · {duration_text}</div></div>"
        )
    return _TIMELINE_CSS + "".join(rows)


def timeline_height(run: "ExecutionRun") -> int:
    return len(run.topology.agents) * 28 + 14
