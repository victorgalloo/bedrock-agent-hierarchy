import pytest

from agent_hierarchy import (
    HUMAN,
    EscalationError,
    HumanQuestion,
    OrgChart,
    Topic,
    check_route,
    escalate,
    escalate_to_human,
)

QUESTION = HumanQuestion(
    question="Approve the yearly docs hosting plan?",
    if_yes="Docs move to the paid plan next week.",
    if_no="Docs stay on the free plan with the current limits.",
)


def test_escalation_goes_one_level_up(org: OrgChart) -> None:
    assert escalate(org, "link-checker", "x").recipient == "docs-writer"
    assert escalate(org, "docs-writer", "x").recipient == "docs-manager"
    assert escalate(org, "docs-manager", "x").recipient == "orchestrator"


def test_orchestrator_cannot_use_plain_escalate(org: OrgChart) -> None:
    with pytest.raises(EscalationError):
        escalate(org, "orchestrator", "x")


@pytest.mark.parametrize(
    ("sender", "recipient"),
    [
        ("docs-writer", "orchestrator"),
        ("link-checker", "docs-manager"),
        ("docs-writer", "triage-manager"),
        ("docs-manager", "release-manager"),
    ],
)
def test_skipping_or_crossing_levels_is_rejected(
    org: OrgChart, sender: str, recipient: str
) -> None:
    with pytest.raises(EscalationError):
        check_route(org, sender, recipient)


@pytest.mark.parametrize("sender", ["docs-manager", "docs-writer", "link-checker"])
def test_only_orchestrator_reaches_a_human(org: OrgChart, sender: str) -> None:
    with pytest.raises(EscalationError, match="only the orchestrator"):
        escalate_to_human(org, sender, Topic.MONEY, QUESTION)


@pytest.mark.parametrize("topic", list(Topic))
def test_orchestrator_reaches_human_on_allowed_topics(org: OrgChart, topic: Topic) -> None:
    esc = escalate_to_human(org, "orchestrator", topic, QUESTION)
    assert esc.recipient == HUMAN
    assert esc.topic is topic


@pytest.mark.parametrize("topic", ["typo-in-docs", "schedule", None])
def test_other_topics_never_reach_a_human(org: OrgChart, topic: str | None) -> None:
    with pytest.raises(EscalationError):
        check_route(org, "orchestrator", HUMAN, topic)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": "Approve the plan."},
        {"question": "Approve the plan? Or the other one?"},
        {"if_yes": " "},
        {"if_no": ""},
        {"action_required": True},
        {"action_required": True, "action_url": "http://example.com/settings"},
    ],
)
def test_human_question_shape(kwargs: dict) -> None:
    base = {"question": "Approve the plan?", "if_yes": "a", "if_no": "b"}
    with pytest.raises(EscalationError):
        HumanQuestion(**{**base, **kwargs})


def test_action_question_carries_a_link() -> None:
    q = HumanQuestion(
        question="Reconnect the docs search account?",
        if_yes="Search works again within the hour.",
        if_no="Search stays down.",
        action_required=True,
        action_url="https://example.com/settings/integrations",
    )
    assert q.action_url
