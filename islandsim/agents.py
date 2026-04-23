from __future__ import annotations

import dataclasses
import random

from pydantic_ai import Agent, RunContext

from islandsim.models import (
    GameSummary,
    NationName,
    SkillRollRecord,
    TurnActions,
    TurnResolution,
    WorldState,
)
from islandsim.prompts import build_country_system_prompt, build_facilitator_system_prompt
from islandsim.rules import skill_roll as _skill_roll
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


@dataclasses.dataclass
class FacilitatorDeps:
    """Per-turn dependencies injected into the facilitator agent.

    Exposes the current world state to tools (so skill lookups use the
    post-rule-engine values for that turn) and collects tool-call records
    so the game loop can attach them to the turn's resolution.
    """

    world_state: WorldState
    roll_log: list[SkillRollRecord] = dataclasses.field(default_factory=list)


def create_agents(
    scenario: ScenarioConfig,
    settings: OperationalConfig,
    rng: random.Random | None = None,
) -> tuple[
    dict[NationName, Agent[None, TurnActions]],
    Agent[FacilitatorDeps, TurnResolution],
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

    facilitator: Agent[FacilitatorDeps, TurnResolution] = Agent(
        settings.models.facilitator,
        output_type=TurnResolution,
        deps_type=FacilitatorDeps,
        system_prompt=facilitator_prompt,
        name="facilitator_agent",
        retries=settings.retries,
    )

    @facilitator.tool
    def skill_roll(
        ctx: RunContext[FacilitatorDeps],
        attacker: NationName,
        defender: NationName,
        difficulty: int,
        context: str,
    ) -> dict:
        """Binding opposed skill roll — call once per resolution event.

        Use for covert-action detection (espionage attempts, secret
        operations). Pass difficulty 0 for routine, +20 for hard, +40
        for extreme. The returned {success, margin} is final — do not
        re-roll, and do not reason around an unwelcome outcome.
        """
        state = ctx.deps.world_state
        attacker_skill = state.nations[attacker].intel_skill
        defender_skill = state.nations[defender].intel_skill
        outcome = _skill_roll(attacker_skill, defender_skill, difficulty, rng=rng)
        ctx.deps.roll_log.append(
            SkillRollRecord(
                attacker=attacker,
                defender=defender,
                difficulty=difficulty,
                attacker_skill=attacker_skill,
                defender_skill=defender_skill,
                roll=outcome.roll,
                margin=outcome.margin,
                success=outcome.success,
                context=context,
            )
        )
        return {"success": outcome.success, "margin": outcome.margin}

    summary = Agent(
        settings.models.facilitator,
        output_type=GameSummary,
        system_prompt=facilitator_prompt,
        name="summary_agent",
        retries=settings.retries,
    )

    return country_agents, facilitator, summary
