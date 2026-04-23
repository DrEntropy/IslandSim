from enum import Enum
from typing import Annotated, Literal, Union

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


class StandardActionType(str, Enum):
    """Standard actions with known resource costs enforced by the rule engine."""

    # Military
    NAVAL_PATROL = "naval_patrol"
    ESTABLISH_BASE = "establish_base"
    NAVAL_BLOCKADE = "naval_blockade"
    DEFENSIVE_POSTURE = "defensive_posture"
    # Economic
    TRADE_SANCTIONS = "trade_sanctions"
    INVEST_INFRASTRUCTURE = "invest_infrastructure"
    ECONOMIC_AID = "economic_aid"
    # Diplomatic
    SOVEREIGNTY_DECLARATION = "sovereignty_declaration"
    APPEAL_INTERNATIONAL = "appeal_international"
    ESPIONAGE = "espionage"
    # Domestic
    RATION_FOOD = "ration_food"
    PROPAGANDA = "propaganda"
    EMERGENCY_FOOD_IMPORTS = "emergency_food_imports"


class Action(BaseModel):
    description: str = Field(description="What the nation is doing")
    visibility: ActionVisibility
    target: NationName | None = Field(
        default=None, description="Target nation, if applicable"
    )
    category: str = Field(
        description="One of: military, economic, diplomatic, domestic"
    )
    action_type: StandardActionType | None = Field(
        default=None,
        description=(
            "Standard action type from the action menu, if this is a standard "
            "action. Use None for creative or custom actions not on the menu."
        ),
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
    intel_skill: int = Field(
        ge=0,
        le=100,
        default=50,
        description=(
            "Intelligence/espionage capability (0-100). Used as both "
            "offense and defense in opposed skill rolls."
        ),
    )


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


class SkillRollRecord(BaseModel):
    """One invocation of the facilitator's skill_roll tool."""

    attacker: NationName
    defender: NationName
    difficulty: int = Field(
        description="0 routine, +20 hard, +40 extreme; subtracted from the attacker's score"
    )
    attacker_skill: int
    defender_skill: int
    roll: int = Field(description="Raw random component of the roll")
    margin: int = Field(description="Final signed score; success if >= 0")
    success: bool
    context: str = Field(
        description="Short facilitator-supplied note naming the resolution event"
    )


ResourceField = Literal["military", "treasury", "food", "support"]


class ResourceChange(BaseModel):
    """Adjust one resource of one nation by a signed delta (clamped 0..100)."""

    kind: Literal["resource"] = "resource"
    nation: NationName
    field: ResourceField
    delta: int
    reason: str = Field(description="Short rationale, used for audit log")


class RelationshipChange(BaseModel):
    """Adjust sentiment between two nations by a signed delta (clamped -100..100)."""

    kind: Literal["relationship"] = "relationship"
    nation_a: NationName
    nation_b: NationName
    delta: int
    reason: str = Field(description="Short rationale, used for audit log")


class StraitChange(BaseModel):
    """Open or close the Naru Strait."""

    kind: Literal["strait"] = "strait"
    open: bool
    reason: str = Field(description="Short rationale, used for audit log")


class ActiveEffectAdd(BaseModel):
    """Add a narrative effect to WorldState.active_effects."""

    kind: Literal["effect_add"] = "effect_add"
    effect: str
    reason: str = Field(description="Short rationale, used for audit log")


class ActiveEffectRemove(BaseModel):
    """Remove an effect from WorldState.active_effects (no-op if absent)."""

    kind: Literal["effect_remove"] = "effect_remove"
    effect: str
    reason: str = Field(description="Short rationale, used for audit log")


class ReefMaruStatusChange(BaseModel):
    """Replace the narrative reef_maru_status string."""

    kind: Literal["reef_maru_status"] = "reef_maru_status"
    new_status: str
    reason: str = Field(description="Short rationale, used for audit log")


StateChange = Annotated[
    Union[
        ResourceChange,
        RelationshipChange,
        StraitChange,
        ActiveEffectAdd,
        ActiveEffectRemove,
        ReefMaruStatusChange,
    ],
    Field(discriminator="kind"),
]


class TurnResolution(BaseModel):
    narrative: str = Field(description="Public narrative of what happened this turn")
    action_results: list[ActionResult]
    changes: list[StateChange] = Field(
        default_factory=list,
        description="Typed state mutations applied by the game engine after resolution",
    )
    event_injected: str | None = Field(
        default=None, description="Random event injected this turn, if any"
    )
    private_intel: dict[NationName, list[str]] = Field(
        default_factory=dict,
        description="Per-nation private information revealed this turn",
    )
    skill_rolls: list[SkillRollRecord] = Field(
        default_factory=list,
        description="All skill_roll tool invocations made during this turn's resolution",
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
    final_state: WorldState = Field(
        description="World state after the rule engine applied the facilitator's changes"
    )


class GameLog(BaseModel):
    """Complete structured log of a game run."""

    timestamp: str = Field(description="ISO 8601 timestamp of game start")
    num_turns: int
    initial_state: WorldState
    turns: list[TurnRecord]
    summary: GameSummary
