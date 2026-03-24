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
from islandsim.prompts import (
    COUNTRY_PROMPTS,
    FACILITATOR_SYSTEM_PROMPT,
)

MODEL = "openrouter:anthropic/claude-sonnet-4-6"


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


# --- Country agents ---

naru_agent = Agent(
    MODEL,
    output_type=TurnActions,
    system_prompt=COUNTRY_PROMPTS[NationName.NARU],
    name="naru_agent",
    retries=2,
)

veldara_agent = Agent(
    MODEL,
    output_type=TurnActions,
    system_prompt=COUNTRY_PROMPTS[NationName.VELDARA],
    name="veldara_agent",
    retries=2,
)

tauma_agent = Agent(
    MODEL,
    output_type=TurnActions,
    system_prompt=COUNTRY_PROMPTS[NationName.TAUMA],
    name="tauma_agent",
    retries=2,
)

COUNTRY_AGENTS: dict[NationName, Agent[None, TurnActions]] = {
    NationName.NARU: naru_agent,
    NationName.VELDARA: veldara_agent,
    NationName.TAUMA: tauma_agent,
}

# --- Facilitator agent ---

facilitator_agent: Agent[None, TurnResolution] = Agent(
    MODEL,
    output_type=TurnResolution,
    system_prompt=FACILITATOR_SYSTEM_PROMPT,
    name="facilitator_agent",
    retries=2,
)

# --- Summary agent (reuses facilitator persona) ---

summary_agent: Agent[None, GameSummary] = Agent(
    MODEL,
    output_type=GameSummary,
    system_prompt=FACILITATOR_SYSTEM_PROMPT,
    name="summary_agent",
    retries=2,
)
