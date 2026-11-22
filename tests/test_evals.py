from pathlib import Path

from agent_hierarchy import OrgChart
from agent_hierarchy.evals import score_fixture

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
