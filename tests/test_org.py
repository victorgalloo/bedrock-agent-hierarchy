import pytest
from pydantic import ValidationError

from agent_hierarchy import Level, OrgChart
from agent_hierarchy.__main__ import main
from tests.conftest import EXAMPLES


def test_example_org_levels_and_parents(org: OrgChart) -> None:
    assert org.level_of("orchestrator") is Level.ORCHESTRATOR
    assert org.parent_of("orchestrator") is None
    assert org.parent_of("docs-manager") == "orchestrator"
    assert org.parent_of("docs-writer") == "docs-manager"
    assert org.parent_of("link-checker") == "docs-writer"
    assert org.manager_of("link-checker") == "docs-manager"
    assert org.manager_of("orchestrator") is None
    assert len(org.names(Level.MANAGER)) == 3


def _minimal(**manager_overrides: object) -> dict:
    manager = {"name": "docs-manager", "area": "docs", "agents": [{"name": "docs-writer"}]}
    manager.update(manager_overrides)
    return {"orchestrator": {"name": "orchestrator"}, "managers": [manager]}


def test_duplicate_names_rejected() -> None:
    data = _minimal(agents=[{"name": "docs-writer"}, {"name": "docs-writer"}])
    with pytest.raises(ValidationError, match="duplicate name"):
        OrgChart.model_validate(data)


def test_duplicate_areas_rejected() -> None:
    data = _minimal()
    data["managers"].append({"name": "other", "area": "docs", "agents": [{"name": "x"}]})
    with pytest.raises(ValidationError, match="duplicate area"):
        OrgChart.model_validate(data)


def test_unknown_keys_and_empty_managers_rejected() -> None:
    with pytest.raises(ValidationError):
        OrgChart.model_validate(_minimal(boss="someone"))
    with pytest.raises(ValidationError):
        OrgChart.model_validate(_minimal(agents=[]))


def test_unknown_member_raises(org: OrgChart) -> None:
    with pytest.raises(KeyError):
        org.parent_of("nobody")


def test_cli_validate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(EXAMPLES / "org.yaml")]) == 0
    assert capsys.readouterr().out.startswith("ok: 1 orchestrator, 3 manager")
    assert main([]) == 2
