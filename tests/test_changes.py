from datetime import date, timedelta
from pathlib import Path

import pytest

from agent_hierarchy import (
    BusyFileError,
    Change,
    ChangeLimitError,
    ChangeManager,
    Escalation,
    OrgChart,
)
from agent_hierarchy.changes import ChangeStatus

TODAY = date(2026, 1, 15)
WHY = "Writer skipped the prerequisites section twice."
MEASURE = "Pages with a prerequisites section over the next 3 runs."


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    (root / "prompts").mkdir(parents=True)
    (root / "skills").mkdir()
    (root / "prompts" / "docs-writer.md").write_text("v1\n")
    (root / "prompts" / "release-notes.md").write_text("v1\n")
    (root / "skills" / "style-guide.md").write_text("v1\n")
    return root


@pytest.fixture
def cm(org: OrgChart, workspace: Path, tmp_path: Path) -> ChangeManager:
    return ChangeManager(org, workspace, tmp_path / "state", evaluate_after_runs=3)


def _args(path: str, kw: dict) -> dict:
    defaults = {"reviewer": "docs-manager", "run_id": "r1", "agent": "docs-writer"}
    return defaults | {"path": path, "why": WHY, "measure": MEASURE, "today": TODAY} | kw


def _begin(cm: ChangeManager, path: str = "prompts/docs-writer.md", **kw: object) -> Change:
    return cm.begin(**_args(path, kw))


def _request(cm: ChangeManager, path: str, **kw: object) -> Change | Escalation:
    return cm.request(**_args(path, kw))


def _release_touches_style_guide(cm: ChangeManager, days_ago: int) -> None:
    _begin(
        cm,
        "skills/style-guide.md",
        reviewer="release-manager",
        agent="release-notes",
        today=TODAY - timedelta(days=days_ago),
    )


def test_change_is_backed_up_and_logged_before_edit(cm: ChangeManager, workspace: Path) -> None:
    change = _begin(cm)
    assert Path(change.backup).read_text() == "v1\n"
    assert change.why == WHY and change.measure == MEASURE
    assert [c.id for c in cm.changes()] == [change.id]


def test_revert_restores_backup_after_n_runs(cm: ChangeManager, workspace: Path) -> None:
    target = workspace / "prompts" / "docs-writer.md"
    change = _begin(cm)
    target.write_text("v2\n")

    with pytest.raises(RuntimeError, match="not due"):
        cm.evaluate(change.id, "revert", "1/3 pages")
    for _ in range(3):
        cm.record_run("docs-writer")
    assert [c.id for c in cm.due("docs-manager")] == [change.id]

    closed = cm.evaluate(change.id, "revert", "1/3 pages had the section")
    assert closed.status is ChangeStatus.REVERTED
    assert target.read_text() == "v1\n"
    assert cm.due() == []


def test_keep_leaves_the_edit(cm: ChangeManager, workspace: Path) -> None:
    target = workspace / "prompts" / "docs-writer.md"
    change = _begin(cm)
    target.write_text("v2\n")
    for _ in range(3):
        cm.record_run("docs-writer")
    assert cm.evaluate(change.id, "keep", "3/3 pages").status is ChangeStatus.KEPT
    assert target.read_text() == "v2\n"


def test_evaluation_needs_a_figure(cm: ChangeManager) -> None:
    change = _begin(cm)
    with pytest.raises(ValueError):
        cm.evaluate(change.id, "keep", " ")


def test_at_most_two_changes_per_run(cm: ChangeManager) -> None:
    _begin(cm)
    _begin(cm, "skills/style-guide.md")
    with pytest.raises(ChangeLimitError):
        _begin(cm)
    assert _begin(cm, run_id="r2").run_id == "r2"


@pytest.mark.parametrize("days_ago", [0, 1])
def test_file_touched_by_another_reviewer_is_busy(cm: ChangeManager, days_ago: int) -> None:
    _release_touches_style_guide(cm, days_ago)
    with pytest.raises(BusyFileError) as err:
        _begin(cm, "skills/style-guide.md")
    assert err.value.holder == "release-manager"

    result = _request(cm, "skills/style-guide.md")
    assert isinstance(result, Escalation)
    assert result.recipient == "orchestrator"
    assert "busy" in result.reason


def test_file_touched_two_days_ago_is_free(cm: ChangeManager) -> None:
    _release_touches_style_guide(cm, 2)
    assert isinstance(_request(cm, "skills/style-guide.md"), Change)


def test_own_earlier_change_does_not_make_file_busy(cm: ChangeManager) -> None:
    _begin(cm)
    _begin(cm, run_id="r2")


def test_manager_only_changes_its_own_agents(cm: ChangeManager) -> None:
    with pytest.raises(PermissionError):
        _begin(cm, "prompts/release-notes.md", agent="release-notes")
    with pytest.raises(PermissionError):
        _begin(cm, reviewer="docs-writer")


def test_change_needs_why_and_measure(cm: ChangeManager) -> None:
    with pytest.raises(ValueError):
        _begin(cm, why="")


def test_paths_outside_root_are_rejected(cm: ChangeManager) -> None:
    with pytest.raises(PermissionError):
        _begin(cm, "../outside.md")
