"""Record fictional run events and print each area's history without a model."""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_hierarchy import load_org
from agent_hierarchy.evals import record_run, score_trends


def main() -> None:
    org = load_org(Path(__file__).with_name("org.yaml"))
    with TemporaryDirectory() as directory:
        recordings = Path(directory)
        for day, recipient in [(1, "human"), (2, "docs-manager")]:
            record_run(
                recordings / f"docs-{day}.json",
                area="docs",
                name=f"docs-review-{day}",
                recorded_at=datetime(2026, 1, day, tzinfo=UTC),
                events=[{"type": "escalation", "sender": "docs-writer", "recipient": recipient}],
            )
        trends = score_trends(org, recordings.glob("*.json"))
        for area, entries in trends.items():
            for entry in entries:
                result = "pass" if entry.score.passed else "fail"
                print(f"{area} {entry.recorded_at.date()} {entry.score.name}: {result}")


if __name__ == "__main__":
    main()
