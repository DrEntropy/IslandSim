from enum import Enum

from pydantic import BaseModel, Field


class NationName(str, Enum):
    NARU = "naru"
    VELDARA = "veldara"
    TAUMA = "tauma"


class Resources(BaseModel):
    military: int = Field(ge=0, le=100, description="Naval strength and troop readiness")
    treasury: int = Field(ge=0, le=100, description="Wealth available for spending")
    food: int = Field(ge=0, le=100, description="Food stockpiles + production")
    support: int = Field(ge=0, le=100, description="Domestic public approval")


class Relationship(BaseModel):
    nation_a: NationName
    nation_b: NationName
    sentiment: int = Field(
        ge=-100,
        le=100,
        default=0,
        description="Sentiment from -100 (hostile) to +100 (allied)",
    )


class ActionVisibility(str, Enum):
    PUBLIC = "public"
    SECRET = "secret"


class Action(BaseModel):
    description: str = Field(description="What the nation is doing")
    visibility: ActionVisibility
    target: NationName | None = Field(
        default=None, description="Target nation, if applicable"
    )
    category: str = Field(
        description="One of: military, economic, diplomatic, domestic"
    )


class TurnActions(BaseModel):
    nation: NationName
    actions: list[Action] = Field(min_length=1, max_length=3)
    reasoning: str = Field(
        description="Internal strategic reasoning (not shared with other agents)"
    )


class NationState(BaseModel):
    name: NationName
    resources: Resources
    traits: str = Field(description="Brief personality and situation description")


class WorldState(BaseModel):
    turn: int
    max_turns: int
    nations: dict[NationName, NationState]
    relationships: list[Relationship]
    reef_maru_status: str = Field(
        description="Narrative description of Reef Maru sovereignty/control"
    )
    active_effects: list[str] = Field(
        default_factory=list,
        description="Ongoing effects from previous turns",
    )
    strait_open: bool = Field(
        default=True, description="Whether Naru Strait is open for trade"
    )


class ActionResult(BaseModel):
    nation: NationName
    action_description: str
    outcome: str
    resource_changes: dict[NationName, dict[str, int]] = Field(
        default_factory=dict,
        description="Resource changes per nation, e.g. {naru: {military: -10}}",
    )
    detected_by: list[NationName] = Field(
        default_factory=list,
        description="Nations that detected this secret action",
    )


class TurnResolution(BaseModel):
    narrative: str = Field(description="Public narrative of what happened this turn")
    action_results: list[ActionResult]
    updated_state: WorldState
    event_injected: str | None = Field(
        default=None, description="Random event injected this turn, if any"
    )
    private_intel: dict[NationName, list[str]] = Field(
        default_factory=dict,
        description="Per-nation private information revealed this turn",
    )


class GameSummary(BaseModel):
    narrative: str = Field(description="Overall narrative summary of the game")
    nation_assessments: dict[NationName, str] = Field(
        description="Per-nation assessment of outcome"
    )
    reef_maru_outcome: str = Field(
        description="Final status of the Reef Maru dispute"
    )


class TurnRecord(BaseModel):
    """All data for a single game turn."""

    turn: int
    actions: dict[NationName, TurnActions]
    resolution: TurnResolution


class GameLog(BaseModel):
    """Complete structured log of a game run."""

    timestamp: str = Field(description="ISO 8601 timestamp of game start")
    num_turns: int
    initial_state: WorldState
    turns: list[TurnRecord]
    summary: GameSummary
