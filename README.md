# bedrock-agent-hierarchy

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/victorgalloo/bedrock-agent-hierarchy)
[![CI](https://github.com/victorgalloo/bedrock-agent-hierarchy/actions/workflows/ci.yml/badge.svg)](https://github.com/victorgalloo/bedrock-agent-hierarchy/actions/workflows/ci.yml)

English | [Español](README.es.md)

> **Status: early.** v0 scaffold. APIs will change.

A small, typed Python template for **manager → sub-agent hierarchies on Amazon Bedrock**.

## What and why

When scheduled agent routines pass a hundred, the hard part stops being "does each one work" and
becomes **"who notices when one stops working"**. This project extracts a pattern that runs in
production (100+ scheduled routines): an **orchestrator** that decides alone, **area managers** that
own an outcome, **agents** that do the work and **sub-agents** that do one thing each.

Managers never message a person. They report to the orchestrator, and only a fixed set of
decisions reaches a human, as one yes/no question.

```mermaid
flowchart TD
    H([Human]) ~~~ O
    O[Orchestrator] -. "yes/no question<br/>(fixed topics only)" .-> H
    O --> M1[docs-manager]
    O --> M2[triage-manager]
    O --> M3[release-manager]
    M1 --> A1[docs-writer]
    M2 --> A2[issue-triager]
    M3 --> A3[release-notes]
    A1 --> S1[link-checker]
    A2 --> S2[duplicate-finder]
    A1 -. escalates .-> M1
    M1 -. escalates .-> O
```

## Quick start

```bash
pip install -e ".[dev]"            # add ",bedrock" for boto3
python -m agent_hierarchy validate examples/org.yaml
pytest
```

```python
from agent_hierarchy import ChangeManager, HumanQuestion, Topic, escalate, escalate_to_human, load_org

org = load_org("examples/org.yaml")
escalate(org, "docs-writer", "two failed runs in a row")      # -> docs-manager

escalate_to_human(org, "orchestrator", Topic.MONEY, HumanQuestion(
    question="Approve the yearly docs hosting plan?",
    if_yes="Docs move to the paid plan next week.",
    if_no="Docs stay on the free plan with the current limits.",
))

cm = ChangeManager(org, root="examples", state_dir=".agent_hierarchy")
change = cm.request("docs-manager", "run-1", "docs-writer", "prompts/docs-writer.md",
                    why="Skipped prerequisites twice", measure="Pages with prerequisites, next 3 runs")
# Change -> edit the file now; Escalation -> the file was busy, sent to the orchestrator.
```

Models run through the Bedrock Converse API (`BedrockModel("<claude-model-id-or-inference-profile>")`);
tests use `FakeModel` and never touch the network.

## Send a Bedrock tool result

Use `BedrockModel.converse_with_tools(system, transcript, tool_config)` with a
tool-capable model and a native Bedrock `toolConfig` dictionary (including `tools`).
The adapter sends one Converse request and returns the assistant's full message and
stop reason. It never executes tools. The text-only `converse` API is unchanged.

This example assumes a single request for the fictional, read-only `lookup_docs` tool.
Validate the tool name and input in your application before executing any tool.

```python
turn = model.converse_with_tools(system, transcript, tool_config)
if turn.stop_reason == "tool_use":
    request = next(block["toolUse"] for block in turn.message["content"] if "toolUse" in block)
    if request["name"] == "lookup_docs" and request["input"] == {"page": "setup"}:
        reply = {
            "role": "user",
            "content": [{"toolResult": {
                "toolUseId": request["toolUseId"],
                "content": [{"json": {"found": True}}],
            }}],
        }
        turn = model.converse_with_tools(system, [*transcript, turn.message, reply], tool_config)
```

Keep the entire assistant message in the transcript, even when it also contains text.
For multiple tool requests, send a matching result block for each ID in one user message.

## Throttling retries and token usage

`BedrockModel` retries throttling errors (`ThrottlingException`, `TooManyRequestsException`,
`Throttling`, `RequestLimitExceeded`, and HTTP 429 responses) with capped exponential backoff
(`max_retries=3`, `retry_base_delay=0.5`, `retry_max_delay=8.0`). Other errors are raised
immediately. Set `max_retries=0` to disable adapter retries when relying on `boto3`'s own retry
configuration.

Each successful Converse response that includes a `usage` block updates `model.last_usage` and
accumulates into `model.total_usage` (`TokenUsage`). `converse_with_tools` also exposes the turn's
usage on `turn.usage`, and an optional `on_usage` callback receives each `TokenUsage` as it arrives:

```python
from agent_hierarchy.bedrock import BedrockModel, TokenUsage

def log_usage(usage: TokenUsage) -> None:
    print(f"tokens: in={usage.input_tokens} out={usage.output_tokens} total={usage.total_tokens}")

model = BedrockModel("us.example-profile-id", max_retries=3, on_usage=log_usage)
reply = model.converse("Review the fictional docs area.", [{"role": "user", "text": "Status?"}])
print(model.total_usage)
```

## Monitor an area without calling a model

Run the fictional docs-area example twice from the repository root:

```bash
python examples/monitor_area.py .agent_hierarchy/demo/docs.json
python examples/monitor_area.py .agent_hierarchy/demo/docs.json
```

On a fresh path, the first check reports `wake: first run`; the same inputs then report `skip`.
In a scheduled job, call `collect_snapshot` with the check date and one area's routine run history
(oldest first, including runs from before the last check if needed to see consecutive failures).
Pass IDs for currently blocked routines, detected KPI drops and conflicting agents, plus the
open-request count. The caller reads its logs and decides what counts as a KPI drop or conflict.

Use a separate snapshot path for each area. In each check, load the previous snapshot, call
`should_wake`, and save the current snapshot after handling the decision, even on a skip. Saving on
a skip lets a cleared exception count as new if it returns. A new ISO week or any open request also
wakes the manager. Serialize checks for the same area so they don't overwrite each other's state.

## Replay an evaluation offline

Run `python examples/eval_replay.py` to score a fictional docs review with `FakeModel`.
It prints `docs-review: pass` and makes no network calls.

Use `agent_hierarchy.evals.replay_fixture(org, path, model)` with a JSON fixture containing
`name`, a `system` prompt, and a nonempty `turns` array of user messages in order. Replay adds
the org's member names, reporting lines, and JSON-only instructions to the system prompt.
It sends each turn with all earlier messages to the model. Each reply must be a JSON object
with an `events` array (empty if nothing happened), reporting only new events for that turn:

| Event `type` | Other fields |
|---|---|
| `escalation` | `sender`, `recipient`, optional `topic` (required when the recipient is human) |
| `change` | `reviewer`, `run_id`, `path` |
| `evaluation` | `change`, `verdict` (`keep` or `revert`), optional boolean `restored` (defaults to false) |

Replay also accepts one fenced JSON block surrounded by prose. If a reply is invalid, replay
stops and returns a failing score with the turn number in `Score.error`. An invalid fixture
still raises a validation error. The score checks routes, change counts across turns, and
reported restores; replay never executes events or verifies that an action happened. You can
also pass a configured `BedrockModel`, which sends the prompt and org context to the live
service. Recording live runs and reporting trends are not yet implemented.

## Design rules

1. **Org chart as data.** `org.yaml` is the single source of truth, validated on load.
2. **Escalate one level at a time.** Sub-agent → agent → manager → orchestrator. Only the
   orchestrator may reach a human, and only about: money, legal, external commitments, public posts
   under someone's name, access/sessions, speaking for someone.
3. **One question per human escalation.** Yes/no, with what happens if yes and if no; if an action
   is needed, a link to exactly where it is done.
4. **Reversible changes.** A manager changes at most 2 prompt/skill files of its own agents per run.
   Each change is backed up first, logged with *why* and *how it will be measured*, evaluated after
   N runs (default 3), and restored automatically on "revert".
5. **Busy files.** If another reviewer touched a file today or yesterday, escalate instead of editing.
6. **Wake only on change.** A cheap monitor decides whether a manager run is needed (new exception,
   new week, open request). Otherwise, no model call.

## Layout

| Module | Status |
|---|---|
| `agent_hierarchy/org.py` | Org chart loading and validation |
| `agent_hierarchy/escalation.py` | Escalation routes and human questions |
| `agent_hierarchy/changes.py` | Backup, change limits, busy files, evaluation, restore |
| `agent_hierarchy/monitor.py` | Collects area signals, persists snapshots and decides whether to wake |
| `agent_hierarchy/bedrock.py` | Converse adapter with tool-use messages, throttling retries, token usage + `FakeModel` |
| `agent_hierarchy/evals.py` | Scores recorded events and replays fixtures through a model |

## Links

- Omona open source: <https://omona.tech/open-source>
- [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

Licensed under [Apache-2.0](LICENSE).
