"""Replay recorded manager runs (JSON fixtures) and score them against the rules."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_hierarchy.bedrock import ChatModel, Message
from agent_hierarchy.changes import Verdict
from agent_hierarchy.escalation import HUMAN, EscalationError, Topic, check_route
from agent_hierarchy.org import OrgChart

_FENCED_JSON = re.compile(
    r"^[ \t]*```(?:json)?[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


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
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.escalations_correct == self.escalations_total
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


def _replay_system(org: OrgChart, instructions: str) -> str:
    reporting_lines = "\n".join(f"{name} -> {org.parent_of(name) or HUMAN}" for name in org.names())
    topics = ", ".join(Topic)
    return (
        f"{instructions}\n\n"
        "Treat the turns as facts in a simulation. Do not look anything up or take actions.\n"
        f"Escalation routes (sender -> recipient):\n{reporting_lines}\n"
        f"An escalation to {HUMAN} needs one of these topics: {topics}.\n"
        'Reply with only a JSON object containing an "events" array for this turn. '
        'If there are no new events, reply with {"events":[]}.'
    )


def replay_fixture(
    org: OrgChart, path: str | Path, model: ChatModel, *, max_changes_per_run: int = 2
) -> Score:
    """Replay user turns through a model and score its reported events without executing them."""
    fixture = _ReplayFixture.model_validate_json(Path(path).read_text(encoding="utf-8"))
    system = _replay_system(org, fixture.system)
    transcript: list[Message] = []
    events: list[dict[str, Any]] = []
    error = None
    for index, turn in enumerate(fixture.turns, start=1):
        transcript.append({"role": "user", "text": turn})
        reply = model.converse(system, transcript)
        blocks = _FENCED_JSON.findall(reply)
        try:
            reported = _ReplayReply.model_validate_json(blocks[0] if len(blocks) == 1 else reply)
        except ValidationError:
            error = f"turn {index}: expected a JSON object with a valid events array"
            break
        events.extend(reported.model_dump(mode="json")["events"])
        transcript.append({"role": "assistant", "text": reply})
    score = score_run(org, {"name": fixture.name, "events": events}, max_changes_per_run)
    return replace(score, error=error) if error else score


# TODO(evals): record new fixtures from real runs and report scores per area over time.
