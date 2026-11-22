"""Escalate one level at a time; only the orchestrator talks to a human."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_hierarchy.org import Level, OrgChart

HUMAN = "human"


class Topic(StrEnum):
    """The only topics that may reach a human."""

    MONEY = "money"
    LEGAL = "legal"
    EXTERNAL_COMMITMENT = "external_commitment"
    PUBLIC_POST = "public_post"
    ACCESS = "access"
    SPEAK_FOR_SOMEONE = "speak_for_someone"


class EscalationError(ValueError):
    pass


@dataclass(frozen=True)
class HumanQuestion:
    """One yes/no question, with the consequences of each answer."""

    question: str
    if_yes: str
    if_no: str
    action_required: bool = False
    action_url: str | None = None

    def __post_init__(self) -> None:
        q = self.question.strip()
        if not q.endswith("?") or q.count("?") != 1:
            raise EscalationError("a human escalation is exactly one question ending in '?'")
        if not self.if_yes.strip() or not self.if_no.strip():
            raise EscalationError("state what happens if yes and if no")
        if self.action_required and not self.action_url:
            raise EscalationError("an action needs a link to where it is done")
        if self.action_url and not self.action_url.startswith("https://"):
            raise EscalationError("action_url must be an https:// link")


@dataclass(frozen=True)
class Escalation:
    sender: str
    recipient: str
    reason: str
    topic: Topic | None = None
    question: HumanQuestion | None = None


def check_route(
    org: OrgChart, sender: str, recipient: str, topic: Topic | str | None = None
) -> None:
    """Raise EscalationError unless `sender -> recipient` is a legal escalation."""
    if sender not in org:
        raise EscalationError(f"unknown sender: {sender}")
    if recipient == HUMAN:
        if org.level_of(sender) is not Level.ORCHESTRATOR:
            raise EscalationError(f"{sender} cannot escalate to a human; only the orchestrator can")
        if topic is None:
            raise EscalationError("a human escalation needs a topic")
        try:
            Topic(topic)
        except ValueError:
            raise EscalationError(f"topic not allowed for a human: {topic}") from None
        return
    parent = org.parent_of(sender)
    if recipient != parent:
        raise EscalationError(f"{sender} must escalate to {parent or HUMAN}, not {recipient}")


def escalate(org: OrgChart, sender: str, reason: str) -> Escalation:
    """Escalate to the direct parent in the org chart."""
    if sender not in org:
        raise EscalationError(f"unknown sender: {sender}")
    parent = org.parent_of(sender)
    if parent is None:
        raise EscalationError("the orchestrator escalates with escalate_to_human()")
    return Escalation(sender=sender, recipient=parent, reason=reason)


def escalate_to_human(
    org: OrgChart, sender: str, topic: Topic | str, question: HumanQuestion
) -> Escalation:
    check_route(org, sender, HUMAN, topic)
    return Escalation(
        sender=sender,
        recipient=HUMAN,
        reason=question.question,
        topic=Topic(topic),
        question=question,
    )
