"""Record, replay and score manager runs against the rules."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from agent_hierarchy.bedrock import ChatModel, Message
from agent_hierarchy.changes import Verdict
from agent_hierarchy.escalation import HUMAN, EscalationError, Topic, check_route
from agent_hierarchy.org import OrgChart

_FENCED_JSON = re.compile(
    r"^[ \t]*```(?:json)?[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


class _EvalSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _ReplayFixture(_EvalSchema):
    name: str = Field(min_length=1)
    system: str = Field(min_length=1)
    turns: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)


class _EscalationEvent(_EvalSchema):
    type: Literal["escalation"]
    sender: str
    recipient: str
    topic: str | None = None


class _ChangeEvent(_EvalSchema):
    type: Literal["change"]
    reviewer: str
    run_id: str
    path: str


class _EvaluationEvent(_EvalSchema):
    type: Literal["evaluation"]
    change: str
    verdict: Literal[Verdict.KEEP, Verdict.REVERT]
    restored: bool = False


class _RunEvents(_EvalSchema):
    events: list[
        Annotated[_EscalationEvent | _ChangeEvent | _EvaluationEvent, Field(discriminator="type")]
    ]


class _RecordedRun(_RunEvents):
    area: str = Field(min_length=1)
    name: str = Field(min_length=1)
    recorded_at: AwareDatetime


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


@dataclass(frozen=True)
class RunScore:
    recorded_at: datetime
    score: Score


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


def record_run(
    path: str | Path,
    *,
    area: str,
    name: str,
    recorded_at: datetime,
    events: list[dict[str, Any]],
) -> None:
    """Save the caller's observed events for a completed run to a new JSON file."""
    run = _RecordedRun(area=area, name=name, recorded_at=recorded_at, events=events)
    run.recorded_at = run.recorded_at.astimezone(UTC)
    payload = run.model_dump_json(indent=2, exclude_none=True)
    with Path(path).open("x", encoding="utf-8") as file:
        file.write(payload + "\n")


def score_trends(
    org: OrgChart, paths: Iterable[str | Path], *, max_changes_per_run: int = 2
) -> dict[str, list[RunScore]]:
    """Score recordings by area, oldest first; no model is called."""
    trends: dict[str, list[RunScore]] = defaultdict(list)
    for path in paths:
        run = _RecordedRun.model_validate_json(Path(path).read_text(encoding="utf-8"))
        score = score_run(org, run.model_dump(mode="json"), max_changes_per_run)
        trends[run.area].append(RunScore(run.recorded_at.astimezone(UTC), score))
    for scores in trends.values():
        scores.sort(key=lambda entry: (entry.recorded_at, entry.score.name))
    return dict(trends)


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
            reported = _RunEvents.model_validate_json(blocks[0] if len(blocks) == 1 else reply)
        except ValidationError:
            error = f"turn {index}: expected a JSON object with a valid events array"
            break
        events.extend(reported.model_dump(mode="json")["events"])
        transcript.append({"role": "assistant", "text": reply})
    score = score_run(org, {"name": fixture.name, "events": events}, max_changes_per_run)
    return replace(score, error=error) if error else score
