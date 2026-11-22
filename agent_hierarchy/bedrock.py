"""Model adapters: Amazon Bedrock Converse API and a FakeModel for tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    text: str


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
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": m["role"], "content": [{"text": m["text"]}]} for m in messages],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
        )
        blocks = response["output"]["message"]["content"]
        return "".join(block.get("text", "") for block in blocks)

    # TODO(bedrock): tool use (toolConfig), retries on throttling, token usage reporting.


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
