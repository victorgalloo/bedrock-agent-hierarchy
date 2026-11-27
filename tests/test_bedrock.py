from typing import Any

import pytest

from agent_hierarchy.bedrock import BedrockModel, ConverseMessage, FakeModel, TokenUsage


class StubClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}


def test_bedrock_model_builds_converse_request_without_network() -> None:
    client = StubClient()
    model = BedrockModel("us.example-profile-id", client=client, max_tokens=64)
    assert model.converse("be brief", [{"role": "user", "text": "hi"}]) == "ok"
    (request,) = client.requests
    assert request["modelId"] == "us.example-profile-id"
    assert request["system"] == [{"text": "be brief"}]
    assert request["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert request["inferenceConfig"]["maxTokens"] == 64
    assert "toolConfig" not in request


def test_bedrock_model_round_trips_tool_calls_and_results() -> None:
    class ToolClient(StubClient):
        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            if len(self.requests) == 1:
                return {"output": {"message": assistant}, "stopReason": "tool_use"}
            return {"output": {"message": final}, "stopReason": "end_turn"}

    first: ConverseMessage = {"role": "user", "content": [{"text": "Find the setup guide"}]}
    assistant = {
        "role": "assistant",
        "content": [
            {"text": "I'll check the index."},
            {
                "toolUse": {
                    "toolUseId": "lookup-1",
                    "name": "lookup_docs",
                    "input": {"page": "setup"},
                }
            },
        ],
    }
    result: ConverseMessage = {
        "role": "user",
        "content": [
            {"toolResult": {"toolUseId": "lookup-1", "content": [{"json": {"found": True}}]}}
        ],
    }
    final = {"role": "assistant", "content": [{"text": "The setup guide exists."}]}
    config = {
        "tools": [
            {
                "toolSpec": {
                    "name": "lookup_docs",
                    "inputSchema": {
                        "json": {"type": "object", "properties": {"page": {"type": "string"}}}
                    },
                }
            }
        ],
        "toolChoice": {"auto": {}},
    }
    client = ToolClient()
    model = BedrockModel("us.example-profile-id", client=client)

    turn = model.converse_with_tools("help with docs", [first], config)
    assert turn.stop_reason == "tool_use"
    assert turn.message == assistant
    assert client.requests[0]["toolConfig"] == config
    assert client.requests[0]["messages"] == [first]

    turn = model.converse_with_tools("help with docs", [first, turn.message, result], config)
    assert turn.stop_reason == "end_turn"
    assert turn.message == final
    assert client.requests[1]["messages"] == [first, assistant, result]
    assert client.requests[1]["toolConfig"] == config


def test_fake_model_replays_replies() -> None:
    fake = FakeModel(["first", "second"])
    assert fake.converse("s", []) == "first"
    assert fake.converse("s", []) == "second"
    assert len(fake.calls) == 2


class StubClientError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        }


def test_bedrock_model_retries_throttling_with_capped_backoff() -> None:
    class FlakyClient(StubClient):
        def __init__(self) -> None:
            super().__init__()
            self.outcomes: list[Any] = [
                StubClientError("ThrottlingException", 429),
                StubClientError("TooManyRequestsException", 429),
                StubClientError("RequestLimitExceeded", 429),
                {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}},
            ]

        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    delays: list[float] = []
    client = FlakyClient()
    model = BedrockModel(
        "us.example-profile-id",
        client=client,
        max_retries=3,
        retry_base_delay=0.5,
        retry_max_delay=1.5,
        sleep=delays.append,
    )

    assert model.converse("be brief", [{"role": "user", "text": "hi"}]) == "ok"
    assert len(client.requests) == 4
    assert delays == [0.5, 1.0, 1.5]


def test_bedrock_model_retries_http_429_and_raises_after_exhaustion() -> None:
    class Always429Client(StubClient):
        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            raise StubClientError("SlowDown", 429)

    delays: list[float] = []
    client = Always429Client()
    model = BedrockModel(
        "us.example-profile-id",
        client=client,
        max_retries=2,
        retry_base_delay=0.25,
        retry_max_delay=4.0,
        sleep=delays.append,
    )

    with pytest.raises(StubClientError, match="SlowDown"):
        model.converse("be brief", [{"role": "user", "text": "hi"}])

    assert len(client.requests) == 3
    assert delays == [0.25, 0.5]


@pytest.mark.parametrize(
    "error",
    [
        StubClientError("ValidationException", 400),
        StubClientError("AccessDeniedException", 403),
        RuntimeError("unexpected"),
    ],
)
def test_bedrock_model_does_not_retry_non_throttling_errors(error: Exception) -> None:
    class FailingClient(StubClient):
        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            raise error

    delays: list[float] = []
    client = FailingClient()
    model = BedrockModel("us.example-profile-id", client=client, max_retries=3, sleep=delays.append)

    with pytest.raises(type(error)):
        model.converse("be brief", [{"role": "user", "text": "hi"}])

    assert len(client.requests) == 1
    assert delays == []


def test_bedrock_model_zero_retries_disables_retry() -> None:
    class ThrottledClient(StubClient):
        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            raise StubClientError("ThrottlingException", 429)

    delays: list[float] = []
    client = ThrottledClient()
    model = BedrockModel("us.example-profile-id", client=client, max_retries=0, sleep=delays.append)

    with pytest.raises(StubClientError, match="ThrottlingException"):
        model.converse("be brief", [{"role": "user", "text": "hi"}])

    assert len(client.requests) == 1
    assert delays == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": -1},
        {"retry_base_delay": -0.1},
        {"retry_max_delay": -1.0},
    ],
)
def test_bedrock_model_rejects_negative_retry_settings(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        BedrockModel("us.example-profile-id", client=StubClient(), **kwargs)


def test_bedrock_model_tracks_and_reports_token_usage() -> None:
    class UsageClient(StubClient):
        def __init__(self) -> None:
            super().__init__()
            self.outcomes: list[Any] = [
                StubClientError("ThrottlingException", 429),
                {
                    "output": {"message": {"role": "assistant", "content": [{"text": "one"}]}},
                    "usage": {"inputTokens": 100, "outputTokens": 25, "totalTokens": 125},
                },
                StubClientError("ThrottlingException", 400),
                {
                    "output": {"message": {"role": "assistant", "content": [{"text": "two"}]}},
                    "stopReason": "end_turn",
                    "usage": {"inputTokens": 40, "outputTokens": 10},
                },
                {
                    "output": {"message": {"role": "assistant", "content": [{"text": "three"}]}},
                },
            ]

        def converse(self, **request: Any) -> dict[str, Any]:
            self.requests.append(request)
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    reported: list[TokenUsage] = []
    model = BedrockModel(
        "us.example-profile-id",
        client=UsageClient(),
        sleep=lambda _: None,
        on_usage=reported.append,
    )

    assert model.last_usage is None
    assert model.total_usage == TokenUsage()

    assert model.converse("s", [{"role": "user", "text": "hi"}]) == "one"
    first_usage = TokenUsage(input_tokens=100, output_tokens=25, total_tokens=125)
    assert model.last_usage == first_usage
    assert model.total_usage == first_usage

    turn = model.converse_with_tools(
        "s",
        [{"role": "user", "content": [{"text": "check"}]}],
        {"tools": []},
    )
    second_usage = TokenUsage(input_tokens=40, output_tokens=10, total_tokens=50)
    assert turn.usage == second_usage
    assert model.last_usage == second_usage
    assert model.total_usage == TokenUsage(input_tokens=140, output_tokens=35, total_tokens=175)
    assert reported == [first_usage, second_usage]

    assert model.converse("s", [{"role": "user", "text": "no usage"}]) == "three"
    assert model.last_usage is None
    assert model.total_usage == TokenUsage(input_tokens=140, output_tokens=35, total_tokens=175)
    assert reported == [first_usage, second_usage]
