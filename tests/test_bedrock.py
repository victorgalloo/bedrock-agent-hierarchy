from typing import Any

from agent_hierarchy.bedrock import BedrockModel, ConverseMessage, FakeModel


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
