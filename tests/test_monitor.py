from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_hierarchy.monitor import (
    AreaSnapshot,
    RoutineRun,
    collect_snapshot,
    load_snapshot,
    save_snapshot,
    should_wake,
)


def test_wakes_only_on_change() -> None:
    quiet = AreaSnapshot(iso_week="2026-W03", open_exceptions=frozenset({"e1"}))
    assert should_wake(None, quiet).wake
    assert not should_wake(quiet, quiet).wake
    assert should_wake(quiet, AreaSnapshot("2026-W03", frozenset({"e1", "e2"}))).wake
    assert should_wake(quiet, AreaSnapshot("2026-W04", frozenset({"e1"}))).wake
    assert should_wake(quiet, AreaSnapshot("2026-W03", frozenset({"e1"}), 1)).wake


def test_collect_snapshot_groups_signals_and_uses_latest_runs() -> None:
    runs = [
        RoutineRun("link-checker", False),
        RoutineRun("docs-writer", False),
        RoutineRun("release-notes", False),
        RoutineRun("link-checker", False),
        RoutineRun("docs-writer", False),
        RoutineRun("docs-writer", True),
    ]
    snapshot = collect_snapshot(
        date(2025, 12, 29),
        runs,
        blocked_routines=["link-checker", "link-checker"],
        dropped_kpis=["docs-coverage"],
        conflicting_agents=["docs-writer+release-notes"],
        open_requests=1,
    )
    assert snapshot == AreaSnapshot(
        "2026-W01",
        frozenset(
            {
                "failed-runs:link-checker",
                "blocked:link-checker",
                "kpi-drop:docs-coverage",
                "conflict:docs-writer+release-notes",
            }
        ),
        1,
    )


def test_snapshots_persist_across_scheduled_checks(tmp_path: Path) -> None:
    path = tmp_path / "state" / "docs.json"
    assert load_snapshot(path) is None

    monday = date(2026, 1, 12)
    blocked = collect_snapshot(monday, [], blocked_routines=["link-checker"])
    assert should_wake(load_snapshot(path), blocked).reasons == ("first run",)
    save_snapshot(path, blocked)
    assert load_snapshot(path) == blocked
    assert not should_wake(load_snapshot(path), blocked).wake

    cleared = collect_snapshot(monday, [])
    assert not should_wake(load_snapshot(path), cleared).wake
    save_snapshot(path, cleared)
    assert should_wake(load_snapshot(path), blocked).reasons == (
        "new exceptions: blocked:link-checker",
    )


def test_corrupt_snapshot_is_not_treated_as_first_run(tmp_path: Path) -> None:
    path = tmp_path / "docs.json"
    path.write_text('{"iso_week": "2026-W03", "open_requests": "invalid"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_snapshot(path)


def test_interrupted_save_keeps_previous_snapshot(tmp_path: Path, monkeypatch) -> None:
    import os as _os

    import pytest

    path = tmp_path / "area.json"
    first = collect_snapshot(date(2026, 11, 23), [], blocked_routines=["link-checker"])
    save_snapshot(path, first)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", boom)
    second = collect_snapshot(date(2026, 11, 30), [], blocked_routines=[])
    with pytest.raises(OSError):
        save_snapshot(path, second)

    assert load_snapshot(path) == first
    assert [p.name for p in tmp_path.iterdir()] == ["area.json"]
