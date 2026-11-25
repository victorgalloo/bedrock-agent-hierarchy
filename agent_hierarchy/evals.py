"""Replay recorded manager runs (JSON fixtures) and score them against the rules."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hierarchy.bedrock import ChatModel, Message
from agent_hierarchy.changes import Verdict
from agent_hierarchy.escalation import EscalationError, check_route
from agent_hierarchy.org import OrgChart


class _ReplaySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _ReplayFixture(_ReplaySchema):
    name: str = Field(min_length=1)
    system: str = Field(min_length=1)
    turns: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class _EscalationEvent(_ReplaySchema):
    type: Literal["escalation"]
    sender: str
    recipient: str
    topic: str | None = None


class _ChangeEvent(_ReplaySchema):
    type: Literal["change"]
    reviewer: str
    run_id: str
    path: str


class _EvaluationEvent(_ReplaySchema):
    type: Literal["evaluation"]
    change: str
    verdict: Verdict
    restored: bool = False


class _ReplayReply(_ReplaySchema):
    events: list[
        Annotated[_EscalationEvent | _ChangeEvent | _EvaluationEvent, Field(discriminator="type")]
    ]


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


def replay_fixture(
    org: OrgChart, path: str | Path, model: ChatModel, *, max_changes_per_run: int = 2
) -> Score:
    """Replay user turns through a model and score its reported events without executing them."""
    fixture = _ReplayFixture.model_validate_json(Path(path).read_text(encoding="utf-8"))
    transcript: list[Message] = []
    events: list[dict[str, Any]] = []
    for turn in fixture.turns:
        transcript.append({"role": "user", "text": turn})
        reply = model.converse(fixture.system, transcript)
        events.extend(_ReplayReply.model_validate_json(reply).model_dump(mode="json")["events"])
        transcript.append({"role": "assistant", "text": reply})
    return score_run(org, {"name": fixture.name, "events": events}, max_changes_per_run)


# TODO(evals): record new fixtures from real runs and report scores per area over time.
