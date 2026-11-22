from pathlib import Path

import pytest

from agent_hierarchy import OrgChart, load_org

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def org() -> OrgChart:
    return load_org(EXAMPLES / "org.yaml")
