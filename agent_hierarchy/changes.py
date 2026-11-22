"""Reversible changes to agent prompt/skill files.

Every change is backed up before editing, logged with why and how it will be
measured, evaluated after N runs, and restored automatically on "revert".
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

from agent_hierarchy.escalation import Escalation, escalate
from agent_hierarchy.org import Level, OrgChart


class Verdict(StrEnum):
    KEEP = "keep"
    REVERT = "revert"


class ChangeStatus(StrEnum):
    OPEN = "open"
    KEPT = "kept"
    REVERTED = "reverted"


class ChangeLimitError(RuntimeError):
    pass


class BusyFileError(RuntimeError):
    def __init__(self, path: str, holder: str, day: str) -> None:
        super().__init__(f"{path} is busy: touched by {holder} on {day}")
        self.path = path
        self.holder = holder
        self.day = day


@dataclass
class Change:
    id: str
    reviewer: str
    agent: str
    path: str
    backup: str
    why: str
    measure: str
    day: str
    run_id: str
    evaluate_after_runs: int
    runs_seen: int = 0
    status: ChangeStatus = ChangeStatus.OPEN
    figure: str | None = None

    @property
    def due(self) -> bool:
        return self.status is ChangeStatus.OPEN and self.runs_seen >= self.evaluate_after_runs


class ChangeManager:
    """Applies the change rules for files under `root`; state lives in `state_dir`."""

    def __init__(
        self,
        org: OrgChart,
        root: str | Path,
        state_dir: str | Path,
        *,
        max_changes_per_run: int = 2,
        evaluate_after_runs: int = 3,
    ) -> None:
        self.org = org
        self.root = Path(root).resolve()
        self.state_dir = Path(state_dir)
        self.backup_dir = self.state_dir / "backups"
        self.log_path = self.state_dir / "changes.json"
        self.max_changes_per_run = max_changes_per_run
        self.evaluate_after_runs = evaluate_after_runs

    def changes(self) -> list[Change]:
        if not self.log_path.exists():
            return []
        raw = json.loads(self.log_path.read_text(encoding="utf-8"))
        return [Change(**{**item, "status": ChangeStatus(item["status"])}) for item in raw]

    def busy_holder(self, path: str | Path, reviewer: str, today: date) -> Change | None:
        """A change to `path` by another reviewer today or yesterday, if any."""
        rel = self._relative(path)
        recent = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
        for change in reversed(self.changes()):
            if change.path == rel and change.reviewer != reviewer and change.day in recent:
                return change
        return None

    def begin(
        self,
        reviewer: str,
        run_id: str,
        agent: str,
        path: str | Path,
        *,
        why: str,
        measure: str,
        today: date | None = None,
    ) -> Change:
        """Back up and log a change. Call before editing the file."""
        today = today or date.today()
        if self.org.level_of(reviewer) is not Level.MANAGER:
            raise PermissionError(f"{reviewer} is not a manager")
        if self.org.manager_of(agent) != reviewer or agent == reviewer:
            raise PermissionError(f"{agent} does not report to {reviewer}")
        if not why.strip() or not measure.strip():
            raise ValueError("a change needs both 'why' and 'how it will be measured'")

        rel = self._relative(path)
        source = self.root / rel
        if not source.is_file():
            raise FileNotFoundError(source)

        changes = self.changes()
        used = sum(1 for c in changes if c.reviewer == reviewer and c.run_id == run_id)
        if used >= self.max_changes_per_run:
            raise ChangeLimitError(f"{reviewer} already made {used} changes in run {run_id}")
        holder = self.busy_holder(rel, reviewer, today)
        if holder is not None:
            raise BusyFileError(rel, holder.reviewer, holder.day)

        change_id = f"{today:%Y%m%d}-{len(changes) + 1:04d}"
        backup = self.backup_dir / f"{change_id}-{source.name}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)

        change = Change(
            id=change_id,
            reviewer=reviewer,
            agent=agent,
            path=rel,
            backup=str(backup),
            why=why,
            measure=measure,
            day=today.isoformat(),
            run_id=run_id,
            evaluate_after_runs=self.evaluate_after_runs,
        )
        self._save([*changes, change])
        return change

    def request(
        self,
        reviewer: str,
        run_id: str,
        agent: str,
        path: str | Path,
        *,
        why: str,
        measure: str,
        today: date | None = None,
    ) -> Change | Escalation:
        """Like begin(), but a busy file becomes an escalation instead of an error."""
        try:
            return self.begin(reviewer, run_id, agent, path, why=why, measure=measure, today=today)
        except BusyFileError as busy:
            return escalate(self.org, reviewer, str(busy))

    def record_run(self, agent: str) -> None:
        """Count one completed run of `agent` towards its open changes."""
        changes = self.changes()
        for change in changes:
            if change.agent == agent and change.status is ChangeStatus.OPEN:
                change.runs_seen += 1
        self._save(changes)

    def due(self, reviewer: str | None = None) -> list[Change]:
        return [c for c in self.changes() if c.due and reviewer in (None, c.reviewer)]

    def evaluate(self, change_id: str, verdict: Verdict | str, figure: str) -> Change:
        """Close a due change with the figure that decided it; restore on revert."""
        if not figure.strip():
            raise ValueError("an evaluation needs the figure that decided it")
        verdict = Verdict(verdict)
        changes = self.changes()
        change = next((c for c in changes if c.id == change_id), None)
        if change is None:
            raise KeyError(change_id)
        if not change.due:
            raise RuntimeError(
                f"{change_id} is not due: {change.runs_seen}/{change.evaluate_after_runs} runs"
            )
        if verdict is Verdict.REVERT:
            shutil.copy2(change.backup, self.root / change.path)
            change.status = ChangeStatus.REVERTED
        else:
            change.status = ChangeStatus.KEPT
        change.figure = figure
        self._save(changes)
        return change

    def _relative(self, path: str | Path) -> str:
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise PermissionError(f"{path} is outside {self.root}")
        return full.relative_to(self.root).as_posix()

    def _save(self, changes: list[Change]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([asdict(c) for c in changes], indent=2, ensure_ascii=False)
        self.log_path.write_text(payload + "\n", encoding="utf-8")
