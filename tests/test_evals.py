import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_hierarchy import OrgChart
from agent_hierarchy.bedrock import FakeModel
from agent_hierarchy.evals import replay_fixture, score_fixture

FIXTURES = Path(__file__).parent / "fixtures"


def test_scores_recorded_runs(org: OrgChart) -> None:
    ok = score_fixture(org, FIXTURES / "docs-run-ok.json")
    assert ok.passed
    assert (ok.escalations_correct, ok.escalations_total) == (3, 3)

    bad = score_fixture(org, FIXTURES / "docs-run-bad.json")
    assert not bad.passed
    assert bad.escalations_correct == 0
    assert not bad.change_limit_respected
    assert (bad.reverts_applied, bad.reverts_total) == (0, 1)


@pytest.fixture
def replay_path(tmp_path: Path) -> Path:
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps({"name": "docs", "system": "Report events.", "turns": ["Start.", "Follow up."]}),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("name", ["docs-run-ok", "docs-run-bad"])
def test_replay_scores_events_across_turns(org: OrgChart, replay_path: Path, name: str) -> None:
    recorded_path = FIXTURES / f"{name}.json"
    events = json.loads(recorded_path.read_text(encoding="utf-8"))["events"]
    replies = [json.dumps({"events": batch}) for batch in (events[:-2], events[-2:])]
    model = FakeModel(replies)

    score = replay_fixture(org, replay_path, model)

    assert score == replace(score_fixture(org, recorded_path), name="docs")
    first = {"role": "user", "text": "Start."}
    system = model.calls[0][0]
    assert system.startswith("Report events.")
    assert "docs-manager -> orchestrator" in system
    assert "docs-writer -> docs-manager" in system
    assert "link-checker -> docs-writer" in system
    assert "only a JSON object" in system
    assert model.calls == [
        (system, [first]),
        (
            system,
            [
                first,
                {"role": "assistant", "text": replies[0]},
                {"role": "user", "text": "Follow up."},
            ],
        ),
    ]


def test_replay_accepts_fenced_json_with_surrounding_prose(
    org: OrgChart, replay_path: Path
) -> None:
    reply = '{"events":[{"type":"escalation","sender":"docs-manager","recipient":"orchestrator"}]}'
    model = FakeModel([f"Here is the event:\n```json\n{reply}\n```\nThat is all.", '{"events":[]}'])

    score = replay_fixture(org, replay_path, model)

    assert score.passed
    assert (score.escalations_correct, score.escalations_total) == (1, 1)


def test_replay_reports_prose_on_its_turn(org: OrgChart, replay_path: Path) -> None:
    model = FakeModel(['{"events":[]}', "I don't have access to the docs area."])

    score = replay_fixture(org, replay_path, model)

    assert not score.passed
    assert score.error == "turn 2: expected a JSON object with a valid events array"


@pytest.mark.parametrize(
    "reply",
    [
        "{}",
        '[{"events":[]}]',
        '{"events":[{"type":"unknown"}]}',
        '{"events":[{"type":"change","run_id":"r1","path":"a.md"}]}',
        '{"events":[{"type":"evaluation","change":"c0","verdict":"revert","restored":"false"}]}',
        '```json\n{"events":[]}\n```\n```json\n{"events":[]}\n```',
    ],
)
def test_replay_rejects_invalid_reply(org: OrgChart, replay_path: Path, reply: str) -> None:
    model = FakeModel([reply])
    score = replay_fixture(org, replay_path, model)
    assert not score.passed
    assert score.error == "turn 1: expected a JSON object with a valid events array"
    assert len(model.calls) == 1


def test_replay_rejects_empty_fixture_before_calling_model(
    org: OrgChart, replay_path: Path
) -> None:
    replay_path.write_text('{"name":"docs","system":"Report events.","turns":[]}', encoding="utf-8")
    model = FakeModel([])
    with pytest.raises(ValidationError):
        replay_fixture(org, replay_path, model)
    assert not model.calls
