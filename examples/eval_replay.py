"""Replay a fictional docs review with canned model replies."""

import json
from pathlib import Path

from agent_hierarchy import load_org
from agent_hierarchy.bedrock import FakeModel
from agent_hierarchy.evals import replay_fixture


def main() -> None:
    examples = Path(__file__).resolve().parent
    events = [
        {"type": "escalation", "sender": "docs-manager", "recipient": "orchestrator"},
        {
            "type": "change",
            "reviewer": "docs-manager",
            "run_id": "r1",
            "path": "prompts/docs-writer.md",
        },
    ]
    model = FakeModel([json.dumps({"events": [event]}) for event in events])
    score = replay_fixture(load_org(examples / "org.yaml"), examples / "docs-replay.json", model)
    print(f"{score.name}: {'pass' if score.passed else 'fail'}")


if __name__ == "__main__":
    main()
