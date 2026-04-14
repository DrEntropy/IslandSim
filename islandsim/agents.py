from __future__ import annotations

import dataclasses

from pydantic_ai import Agent

from islandsim.models import (
    GameSummary,
    NationName,
    TurnActions,
    TurnResolution,
    WorldState,
)
from islandsim.prompts import build_country_system_prompt, build_facilitator_system_prompt
from islandsim.scenario import ScenarioConfig
from islandsim.settings import OperationalConfig


@dataclasses.dataclass
class NationContext:
    """Context passed to a country agent for a single turn."""

    nation: NationName
    world_state: WorldState
    own_private_intel: list[str]
    history: list[str]


@dataclasses.dataclass
class FacilitatorContext:
    """Context passed to the facilitator for resolving a turn."""

    world_state: WorldState
    all_actions: dict[NationName, TurnActions]
    history: list[str]
    turns_since_last_event: int
    econ_changes: dict[NationName, dict[str, int]] = dataclasses.field(default_factory=dict)
    applied_costs: list = dataclasses.field(default_factory=list)
    unmatched_actions: list = dataclasses.field(default_factory=list)


def create_agents(
    scenario: ScenarioConfig,
    settings: OperationalConfig,
) -> tuple[
    dict[NationName, Agent[None, TurnActions]],
    Agent[None, TurnResolution],
    Agent[None, GameSummary],
]:
    """Create all game agents from scenario and operational config."""
    country_agents: dict[NationName, Agent[None, TurnActions]] = {}
    for nation in NationName:
        system_prompt = build_country_system_prompt(nation, scenario)
        country_agents[nation] = Agent(
            settings.models.country,
            output_type=TurnActions,
            system_prompt=system_prompt,
            name=f"{nation.value}_agent",
            retries=settings.retries,
        )

    facilitator_prompt = build_facilitator_system_prompt(scenario)

    facilitator = Agent(
        settings.models.facilitator,
        output_type=TurnResolution,
        system_prompt=facilitator_prompt,
        name="facilitator_agent",
        retries=settings.retries,
    )

    summary = Agent(
        settings.models.facilitator,
        output_type=GameSummary,
        system_prompt=facilitator_prompt,
        name="summary_agent",
        retries=settings.retries,
    )

    return country_agents, facilitator, summary
