"""Org chart as data: orchestrator -> managers -> agents -> sub-agents."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

NAME_PATTERN = r"^[a-z][a-z0-9-]*$"


class Level(StrEnum):
    ORCHESTRATOR = "orchestrator"
    MANAGER = "manager"
    AGENT = "agent"
    SUBAGENT = "subagent"


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""


class SubAgent(_Node):
    prompt: str | None = None


class Agent(_Node):
    prompt: str | None = None
    skills: list[str] = Field(default_factory=list)
    schedule: str | None = None
    subagents: list[SubAgent] = Field(default_factory=list)


class Manager(_Node):
    area: str = Field(pattern=NAME_PATTERN)
    agents: list[Agent] = Field(min_length=1)


class Orchestrator(_Node):
    pass


class OrgChart(BaseModel):
    """The tree is the single source of truth for who reports to whom."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    orchestrator: Orchestrator
    managers: list[Manager] = Field(min_length=1)

    _parents: dict[str, str | None] = PrivateAttr(default_factory=dict)
    _levels: dict[str, Level] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _index(self) -> OrgChart:
        entries: list[tuple[str, Level, str | None]] = [
            (self.orchestrator.name, Level.ORCHESTRATOR, None)
        ]
        areas: set[str] = set()
        for manager in self.managers:
            if manager.area in areas:
                raise ValueError(f"duplicate area: {manager.area}")
            areas.add(manager.area)
            entries.append((manager.name, Level.MANAGER, self.orchestrator.name))
            for agent in manager.agents:
                entries.append((agent.name, Level.AGENT, manager.name))
                for sub in agent.subagents:
                    entries.append((sub.name, Level.SUBAGENT, agent.name))

        for name, level, parent in entries:
            if name in self._levels:
                raise ValueError(f"duplicate name: {name}")
            self._levels[name] = level
            self._parents[name] = parent
        return self

    def __contains__(self, name: object) -> bool:
        return name in self._levels

    def level_of(self, name: str) -> Level:
        self._require(name)
        return self._levels[name]

    def parent_of(self, name: str) -> str | None:
        """Who `name` reports to; None for the orchestrator."""
        self._require(name)
        return self._parents[name]

    def manager_of(self, name: str) -> str | None:
        """The manager that owns an agent or sub-agent (or is `name` itself)."""
        current: str | None = name
        while current is not None:
            if self.level_of(current) is Level.MANAGER:
                return current
            current = self.parent_of(current)
        return None

    def names(self, level: Level | None = None) -> list[str]:
        return [n for n, lv in self._levels.items() if level is None or lv is level]

    def _require(self, name: str) -> None:
        if name not in self._levels:
            raise KeyError(f"unknown member of org chart: {name}")


def load_org(path: str | Path) -> OrgChart:
    """Load and validate an `org.yaml` file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return OrgChart.model_validate(data)
