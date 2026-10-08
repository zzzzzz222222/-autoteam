"""Regression tests for AT-AUDIT-002 (ResultStore cross-run state pollution).

Background: ``ResultStore`` outlives a single run (``ResearchOrchestrator`` keeps
one for its whole lifetime). Before v0.6.2 every event was appended to one flat
list and ``status_of`` scanned *all* of it, so a second run could read a previous
run's results/events.

These tests exercise the real isolation behaviour through the public API. They do
not mock ``status_of`` and do not merely assert that a function was called: every
assertion reads back what the store actually filed under each run.
"""

from __future__ import annotations

import threading

from app.runtime.result_store import ResultStore, RunEvent
from app.scheduler.models import AgentResult, ExecutionStatus


def _result(agent_id: str, status: ExecutionStatus) -> AgentResult:
    return AgentResult(agent_id=agent_id, status=status)


def _event(agent_id: str, event: str, run_id: str = "", when: float = 0.0) -> RunEvent:
    return RunEvent(agent_id=agent_id, event=event, timestamp=when, run_id=run_id)


# --- 1. sequential runs on one shared store ---------------------------------

def test_sequential_runs_do_not_share_status():
    """Run A completes, then run B starts: B must not see A's success."""
    store = ResultStore()
    store.start_run("A")
    store.record(_event("writer", "start", "A"))
    store.record(_event("writer", "done", "A"))
    store.set_results({"writer": _result("writer", ExecutionStatus.SUCCESS)}, run_id="A")
    assert store.status_of("writer", "A") == "success"

    store.start_run("B")
    store.record(_event("writer", "start", "B"))
    # "B" has only a start event -> running, never A's "success".
    assert store.status_of("writer", "B") == "running"
    # Default (no run_id) follows the run the store is currently bound to.
    assert store.status_of("writer") == "running"
    # Run A is untouched by everything B did.
    assert store.status_of("writer", "A") == "success"


def test_previous_run_events_are_still_readable_after_new_run_starts():
    """Isolation must not mean deletion: run A keeps its own events."""
    store = ResultStore()
    store.start_run("A")
    store.record(_event("a1", "start", "A"))
    store.record(_event("a1", "done", "A"))
    store.start_run("B")
    store.record(_event("a1", "start", "B"))

    assert [e.event for e in store.events_of("A")] == ["start", "done"]
    assert [e.event for e in store.events_of("B")] == ["start"]
    # The legacy flat list still holds everything (nothing was cleared).
    assert len(store.events) == 3


# --- 2. interleaved writes ---------------------------------------------------

def test_interleaved_writes_keep_attribution_and_order():
    store = ResultStore()
    store.start_run("A")
    store.start_run("B")  # bind B last; ids are still explicit per event
    for run_id, agent in (("A", "x"), ("B", "x"), ("A", "x"), ("B", "x")):
        store.record(_event(agent, "start" if run_id == "A" else "error", run_id))

    a_events = store.events_of("A")
    b_events = store.events_of("B")
    assert [e.run_id for e in a_events] == ["A", "A"]
    assert [e.run_id for e in b_events] == ["B", "B"]
    assert [e.event for e in a_events] == ["start", "start"]
    assert [e.event for e in b_events] == ["error", "error"]


def test_interleaved_runs_status_stays_scoped():
    store = ResultStore()
    store.record(_event("shared", "error", "A"))   # A: failed
    store.record(_event("shared", "start", "B"))   # B: running
    assert store.status_of("shared", "A") == "failed"
    assert store.status_of("shared", "B") == "running"


# --- 3/4. cross-run isolation in both directions ----------------------------

def test_run_a_status_unaffected_by_run_b():
    store = ResultStore()
    store.set_results({"x": _result("x", ExecutionStatus.SUCCESS)}, run_id="A")
    # B later fails the same agent id.
    store.set_results({"x": _result("x", ExecutionStatus.FAILED)}, run_id="B")
    assert store.status_of("x", "A") == "success"
    assert store.status_of("x", "B") == "failed"


def test_run_b_status_unaffected_by_run_a_history():
    store = ResultStore()
    store.start_run("A")
    store.record(_event("x", "start", "A"))
    store.record(_event("x", "done", "A"))
    store.set_results({"x": _result("x", ExecutionStatus.SKIPPED)}, run_id="A")

    store.start_run("B")
    # Nothing recorded for B yet -> pending, not A's "skipped".
    assert store.status_of("x", "B") == "pending"
    assert store.status_of("x", "A") == "skipped"


# --- 5. ordering / status within one run -----------------------------------

def test_single_run_event_order_is_preserved():
    store = ResultStore()
    store.start_run("R")
    store.record(_event("x", "start", "R", when=1.0))
    store.record(_event("x", "done", "R", when=2.0))
    store.record(_event("y", "start", "R", when=1.5))
    store.record(_event("y", "error", "R", when=2.5))

    assert [e.timestamp for e in store.events_of("R")] == [1.0, 2.0, 1.5, 2.5]
    assert store.status_of("x", "R") == "pending"   # done, no result recorded
    assert store.status_of("y", "R") == "failed"


def test_last_event_of_the_run_wins():
    store = ResultStore()
    store.record(_event("x", "start", "R"))
    assert store.status_of("x", "R") == "running"
    store.record(_event("x", "error", "R"))
    assert store.status_of("x", "R") == "failed"


# --- 6. concurrency ---------------------------------------------------------

def test_concurrent_runs_do_not_crossover():
    store = ResultStore()
    barrier = threading.Barrier(4)
    errors: list[str] = []

    def writer(run_id: str, status: ExecutionStatus) -> None:
        try:
            barrier.wait()
            for index in range(25):
                store.record(_event(f"agent_{run_id}", "start", run_id, when=float(index)))
            store.set_results(
                {f"agent_{run_id}": _result(f"agent_{run_id}", status)}, run_id=run_id
            )
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(f"{run_id}: {exc}")

    threads = [
        threading.Thread(target=writer, args=("A", ExecutionStatus.SUCCESS)),
        threading.Thread(target=writer, args=("B", ExecutionStatus.FAILED)),
        threading.Thread(target=writer, args=("C", ExecutionStatus.SKIPPED)),
        threading.Thread(target=writer, args=("D", ExecutionStatus.SUCCESS)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(store.runs()) == ["A", "B", "C", "D"]
    for run_id in ("A", "B", "C", "D"):
        events = store.events_of(run_id)
        assert len(events) == 25, f"run {run_id} lost/leaked events"
        assert all(event.run_id == run_id for event in events)
        assert all(event.agent_id == f"agent_{run_id}" for event in events)
    assert store.status_of("agent_A", "A") == "success"
    assert store.status_of("agent_B", "B") == "failed"
    assert store.status_of("agent_C", "C") == "skipped"
    # A concurrent run never reads another run's result.
    assert store.status_of("agent_A", "B") == "pending"


def test_concurrent_runs_never_delete_each_other():
    """A run starting mid-flight must not clear another run's events."""
    store = ResultStore()
    store.start_run("A")
    for index in range(10):
        store.record(_event("a", "start", "A", when=float(index)))
    store.start_run("B")  # binds a new run while A is still "in flight"
    store.record(_event("b", "start", "B"))
    assert len(store.events_of("A")) == 10
    assert len(store.events_of("B")) == 1


# --- 7. backward compatibility ---------------------------------------------

def test_unbound_store_keeps_legacy_aggregate_behaviour():
    """A store that never binds a run behaves exactly as before v0.6.2."""
    store = ResultStore()
    store.record(RunEvent(agent_id="x", event="start", timestamp=1.0))
    assert store.status_of("x") == "running"
    store.record(RunEvent(agent_id="x", event="error", timestamp=2.0))
    assert store.status_of("x") == "failed"
    store.set_results({"x": _result("x", ExecutionStatus.SUCCESS)})
    assert store.status_of("x") == "success"
    snapshot = store.snapshot()
    assert len(snapshot["events"]) == 2
    assert snapshot["results"]["x"]["status"] == "success"


def test_events_without_run_id_remain_supported():
    """``run_id`` defaults to "" so existing constructors keep working."""
    event = RunEvent(agent_id="x", event="done", timestamp=0.0)
    assert event.run_id == ""
    store = ResultStore()
    store.record(event)
    assert store.status_of("x", "") == "pending"
    assert len(store.events_of("")) == 1
    assert event.run_id == ""   # empty stays empty; nothing is invented


def test_snapshot_is_run_scoped():
    store = ResultStore()
    store.record(_event("x", "start", "A"))
    store.set_results({"x": _result("x", ExecutionStatus.SUCCESS)}, run_id="A")
    store.record(_event("x", "start", "B"))

    a_snapshot = store.snapshot("A")
    assert len(a_snapshot["events"]) == 1
    assert a_snapshot["events"][0]["run_id"] == "A"
    assert a_snapshot["results"]["x"]["status"] == "success"

    b_snapshot = store.snapshot("B")
    assert len(b_snapshot["events"]) == 1
    assert b_snapshot["events"][0]["run_id"] == "B"
    assert b_snapshot["results"] == {}


def test_record_stamps_ownership_from_event_or_argument():
    store = ResultStore()
    store.record(_event("x", "start", "given"))
    assert store.events_of("given")[0].run_id == "given"

    # An explicit argument wins over the event's (empty) id.
    plain = RunEvent(agent_id="y", event="start", timestamp=0.0)
    store.record(plain, run_id="explicit")
    assert plain.run_id == "explicit"
    assert store.status_of("y", "explicit") == "running"


# --- 8. failure / retry / skipped statuses ---------------------------------

def test_failure_retry_and_skipped_statuses_are_scoped():
    store = ResultStore()
    store.start_run("A")
    store.set_results(
        {
            "failed_agent": _result("failed_agent", ExecutionStatus.FAILED),
            "skipped_agent": _result("skipped_agent", ExecutionStatus.SKIPPED),
        },
        run_id="A",
    )
    assert store.status_of("failed_agent", "A") == "failed"
    assert store.status_of("skipped_agent", "A") == "skipped"

    # Same agent ids, new run, still in flight -> derived from that run only.
    store.start_run("B")
    store.record(_event("failed_agent", "start", "B"))
    store.record(_event("skipped_agent", "error", "B"))
    assert store.status_of("failed_agent", "B") == "running"
    assert store.status_of("skipped_agent", "B") == "failed"


def test_successful_retry_is_reported_as_success_for_its_run():
    """A retry only changes the run it belongs to."""
    store = ResultStore()
    store.start_run("A")
    store.record(_event("x", "error", "A"))
    store.set_results({"x": _result("x", ExecutionStatus.SUCCESS)}, run_id="A")
    assert store.status_of("x", "A") == "success"

    store.start_run("B")
    store.record(_event("x", "error", "B"))
    assert store.status_of("x", "B") == "failed"
    assert store.status_of("x", "A") == "success"
