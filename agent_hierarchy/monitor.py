"""Wake a manager only when something changed; otherwise no model call."""

from __future__ import annotations

from dataclasses import dataclass, field


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


# TODO(monitor): collectors that build an AreaSnapshot from real run logs
# (two failed runs in a row, blocked routine, KPI drop, conflicting agents),
# and persistence of the previous snapshot between scheduled runs.
