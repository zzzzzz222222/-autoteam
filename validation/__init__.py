"""AutoTeam v0.6.0 validation toolkit.

Offline-first infrastructure for repeatable, auditable *real scenario* runs.
This package is intentionally decoupled from the core engine: it imports the
public entry points (``execute_task``, providers, tools, models) and never
modifies them.
"""

__all__ = ["scenarios"]
