"""Wake a manager only when something changed; otherwise no model call."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter


@dataclass(frozen=True)
class AreaSnapshot:
    """Cheap facts about one area, collected without calling a model."""

    iso_week: str
    open_exceptions: frozenset[str] = field(default_factory=frozenset)
    open_requests: int = 0


@dataclass(frozen=True)
class WakeDecision:
    wake: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutineRun:
    routine: str
    succeeded: bool


def collect_snapshot(
    day: date,
    runs: Iterable[RoutineRun],
    *,
    blocked_routines: Iterable[str] = (),
    dropped_kpis: Iterable[str] = (),
    conflicting_agents: Iterable[str] = (),
    open_requests: int = 0,
) -> AreaSnapshot:
    """Collect one area's signals; runs must be ordered oldest first."""
    failures: dict[str, int] = {}
    for run in runs:
        failures[run.routine] = 0 if run.succeeded else failures.get(run.routine, 0) + 1

    exceptions = {f"failed-runs:{routine}" for routine, count in failures.items() if count >= 2}
    exceptions.update(f"blocked:{routine}" for routine in blocked_routines)
    exceptions.update(f"kpi-drop:{kpi}" for kpi in dropped_kpis)
    exceptions.update(f"conflict:{conflict}" for conflict in conflicting_agents)

    year, week, _ = day.isocalendar()
    return AreaSnapshot(f"{year:04d}-W{week:02d}", frozenset(exceptions), open_requests)


_SNAPSHOT_ADAPTER = TypeAdapter(AreaSnapshot)


def load_snapshot(path: str | Path) -> AreaSnapshot | None:
    """Read the previous snapshot, or return None if it does not exist."""
    try:
        payload = Path(path).read_bytes()
    except FileNotFoundError:
        return None
    return _SNAPSHOT_ADAPTER.validate_json(payload, strict=True)


def save_snapshot(path: str | Path, snapshot: AreaSnapshot) -> None:
    """Persist the snapshot for the next scheduled check."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iso_week": snapshot.iso_week,
        "open_exceptions": sorted(snapshot.open_exceptions),
        "open_requests": snapshot.open_requests,
    }
    # Write to a temp file in the same directory, then atomically replace the target, so an
    # interrupted save never leaves a truncated JSON behind (load_snapshot keeps reading the old one).
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def should_wake(previous: AreaSnapshot | None, current: AreaSnapshot) -> WakeDecision:
    reasons: list[str] = []
    if previous is None:
        reasons.append("first run")
    else:
        new = current.open_exceptions - previous.open_exceptions
        if new:
            reasons.append(f"new exceptions: {', '.join(sorted(new))}")
        if current.iso_week != previous.iso_week:
            reasons.append(f"new week: {current.iso_week}")
    if current.open_requests:
        reasons.append(f"open requests: {current.open_requests}")
    return WakeDecision(wake=bool(reasons), reasons=tuple(reasons))
