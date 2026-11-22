from typing import Any

from agent_hierarchy.bedrock import BedrockModel, FakeModel


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


def test_fake_model_replays_replies() -> None:
    fake = FakeModel(["first", "second"])
    assert fake.converse("s", []) == "first"
    assert fake.converse("s", []) == "second"
    assert len(fake.calls) == 2
