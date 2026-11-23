"""Check a fictional area without a model, reusing one snapshot file across runs."""

from argparse import ArgumentParser
from datetime import date
from pathlib import Path

from agent_hierarchy.monitor import (
    RoutineRun,
    collect_snapshot,
    load_snapshot,
    save_snapshot,
    should_wake,
)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    path = parser.parse_args().snapshot

    current = collect_snapshot(
        date(2026, 1, 12),
        [RoutineRun("link-checker", False), RoutineRun("link-checker", False)],
    )
    decision = should_wake(load_snapshot(path), current)
    print(f"wake: {'; '.join(decision.reasons)}" if decision.wake else "skip")
    save_snapshot(path, current)


if __name__ == "__main__":
    main()
