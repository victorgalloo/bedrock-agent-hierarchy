"""Model adapters: Amazon Bedrock Converse API and a FakeModel for tests."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

_THROTTLING_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "Throttling",
        "RequestLimitExceeded",
    }
)


class Message(TypedDict):
    role: Literal["user", "assistant"]
    text: str


class ConverseMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: list[dict[str, Any]]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class ToolTurn:
    message: ConverseMessage
    stop_reason: str
    usage: TokenUsage | None = None


class ChatModel(Protocol):
    def converse(self, system: str, messages: Sequence[Message]) -> str: ...


def _is_throttling(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if isinstance(error, dict) and error.get("Code") in _THROTTLING_CODES:
        return True
    meta = response.get("ResponseMetadata")
    return isinstance(meta, dict) and meta.get("HTTPStatusCode") == 429


def _parse_usage(response: dict[str, Any]) -> TokenUsage | None:
    raw = response.get("usage")
    if not isinstance(raw, dict):
        return None
    input_tokens = int(raw.get("inputTokens") or 0)
    output_tokens = int(raw.get("outputTokens") or 0)
    raw_total = raw.get("totalTokens")
    total_tokens = input_tokens + output_tokens if raw_total is None else int(raw_total)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


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
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
        retry_max_delay: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
        on_usage: Callable[[TokenUsage], None] | None = None,
        client: Any | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if retry_base_delay < 0 or retry_max_delay < 0:
            raise ValueError("retry delays must be >= 0")
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self._sleep = sleep
        self._on_usage = on_usage
        self.last_usage: TokenUsage | None = None
        self.total_usage: TokenUsage = TokenUsage()
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
        return ToolTurn(response["output"]["message"], response["stopReason"], self.last_usage)

    def _converse(
        self, system: str, messages: Sequence[ConverseMessage], **options: Any
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": system}],
                    messages=list(messages),
                    inferenceConfig={
                        "maxTokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                    **options,
                )
                break
            except Exception as exc:
                if attempt >= self.max_retries or not _is_throttling(exc):
                    raise
                delay = min(self.retry_base_delay * (2**attempt), self.retry_max_delay)
                self._sleep(delay)

        usage = _parse_usage(response)
        self.last_usage = usage
        if usage is not None:
            self.total_usage = self.total_usage + usage
            if self._on_usage is not None:
                self._on_usage(usage)
        return response


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
