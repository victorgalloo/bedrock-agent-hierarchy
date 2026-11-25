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
    assert model.calls == [
        ("Report events.", [first]),
        (
            "Report events.",
            [
                first,
                {"role": "assistant", "text": replies[0]},
                {"role": "user", "text": "Follow up."},
            ],
        ),
    ]


@pytest.mark.parametrize(
    "reply",
    [
        "not JSON",
        "{}",
        '{"events":[{"type":"unknown"}]}',
        '{"events":[{"type":"change","run_id":"r1","path":"a.md"}]}',
        '{"events":[{"type":"evaluation","change":"c0","verdict":"revert","restored":"false"}]}',
    ],
)
def test_replay_rejects_invalid_reply(org: OrgChart, replay_path: Path, reply: str) -> None:
    model = FakeModel([reply])
    with pytest.raises(ValidationError):
        replay_fixture(org, replay_path, model)
    assert len(model.calls) == 1


def test_replay_rejects_empty_fixture_before_calling_model(
    org: OrgChart, replay_path: Path
) -> None:
    replay_path.write_text('{"name":"docs","system":"Report events.","turns":[]}', encoding="utf-8")
    model = FakeModel([])
    with pytest.raises(ValidationError):
        replay_fixture(org, replay_path, model)
    assert not model.calls
