"""Model adapters: Amazon Bedrock Converse API and a FakeModel for tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    text: str


class ConverseMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: list[dict[str, Any]]


@dataclass(frozen=True)
class ToolTurn:
    message: ConverseMessage
    stop_reason: str


class ChatModel(Protocol):
    def converse(self, system: str, messages: Sequence[Message]) -> str: ...


class BedrockModel:
    """Calls `bedrock-runtime` Converse.

    `model_id` may be a foundation model ID (e.g. a Claude model ID) or an
    inference profile ID/ARN (e.g. a cross-region `us.` / `eu.` profile).
    """

    def __init__(
        self,
        model_id: str,
        *,
        region: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        client: Any | None = None,
    ) -> None:
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        if client is None:
            import boto3  # optional dependency: pip install "bedrock-agent-hierarchy[bedrock]"

            client = boto3.client("bedrock-runtime", region_name=region)
        self.client = client

    def converse(self, system: str, messages: Sequence[Message]) -> str:
        transcript: list[ConverseMessage] = [
            {"role": m["role"], "content": [{"text": m["text"]}]} for m in messages
        ]
        response = self._converse(system, transcript)
        blocks = response["output"]["message"]["content"]
        return "".join(block.get("text", "") for block in blocks)

    def converse_with_tools(
        self,
        system: str,
        messages: Sequence[ConverseMessage],
        tool_config: dict[str, Any],
    ) -> ToolTurn:
        """Send one turn using native Bedrock blocks; never execute tools."""
        response = self._converse(system, messages, toolConfig=tool_config)
        return ToolTurn(response["output"]["message"], response["stopReason"])

    def _converse(
        self, system: str, messages: Sequence[ConverseMessage], **options: Any
    ) -> dict[str, Any]:
        return self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=list(messages),
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
            **options,
        )

    # TODO(bedrock): retries on throttling, token usage reporting.


class FakeModel:
    """Deterministic model for tests: replays canned replies or calls a function."""

    def __init__(self, replies: Sequence[str] | Callable[[str, Sequence[Message]], str]) -> None:
        self._replies = replies if callable(replies) else list(replies)
        self.calls: list[tuple[str, list[Message]]] = []

    def converse(self, system: str, messages: Sequence[Message]) -> str:
        self.calls.append((system, list(messages)))
        if callable(self._replies):
            return self._replies(system, messages)
        if not self._replies:
            raise RuntimeError("FakeModel ran out of replies")
        return self._replies.pop(0)
