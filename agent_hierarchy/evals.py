"""Replay recorded manager runs (JSON fixtures) and score them against the rules."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_hierarchy.escalation import EscalationError, check_route
from agent_hierarchy.org import OrgChart


@dataclass(frozen=True)
class Score:
    name: str
    escalations_correct: int
    escalations_total: int
    change_limit_respected: bool
    reverts_applied: int
    reverts_total: int

    @property
    def passed(self) -> bool:
        return (
            self.escalations_correct == self.escalations_total
            and self.change_limit_respected
            and self.reverts_applied == self.reverts_total
        )


def score_run(org: OrgChart, run: dict[str, Any], max_changes_per_run: int = 2) -> Score:
    events: list[dict[str, Any]] = run["events"]
    escalations = [e for e in events if e["type"] == "escalation"]
    correct = 0
    for e in escalations:
        try:
            check_route(org, e["sender"], e["recipient"], e.get("topic"))
            correct += 1
        except EscalationError:
            pass

    per_run = Counter((e["reviewer"], e["run_id"]) for e in events if e["type"] == "change")
    reverts = [e for e in events if e["type"] == "evaluation" and e["verdict"] == "revert"]
    return Score(
        name=run["name"],
        escalations_correct=correct,
        escalations_total=len(escalations),
        change_limit_respected=all(n <= max_changes_per_run for n in per_run.values()),
        reverts_applied=sum(1 for e in reverts if e.get("restored")),
        reverts_total=len(reverts),
    )


def score_fixture(org: OrgChart, path: str | Path) -> Score:
    return score_run(org, json.loads(Path(path).read_text(encoding="utf-8")))


# TODO(evals): replay fixtures through a manager loop driven by FakeModel/BedrockModel,
# record new fixtures from real runs, and report scores per area over time.
