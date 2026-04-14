"""Scenario configuration loader.

Loads scenario data from YAML files in the scenarios/ directory and
provides typed access via Pydantic models.
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from islandsim.models import (
    NationName,
    NationState,
    Relationship,
    Resources,
    StandardActionType,
    WorldState,
)
from islandsim.rules import ActionCost


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class ScenarioMeta(BaseModel):
    name: str
    description: str


class GameConfig(BaseModel):
    max_turns: int = 8
    event_injection_guidance: str = "every 2-3 turns"
    instability_threshold: int = 25


class NationEconomy(BaseModel):
    treasury_income: int
    requires_strait_for_income: bool = False
    food_production: int


class NationConfig(BaseModel):
    traits: str
    personality: str
    resources: Resources
    economy: NationEconomy


class ActionCostConfig(BaseModel):
    actor: dict[str, int] = Field(default_factory=dict)
    target: dict[str, int] | None = None
    requires_strait: bool = False


class StartingConditions(BaseModel):
    reef_maru_status: str
    active_effects: list[str] = Field(default_factory=list)
    strait_open: bool = True


class ScenarioConfig(BaseModel):
    meta: ScenarioMeta
    game: GameConfig = Field(default_factory=GameConfig)
    nations: dict[str, NationConfig]
    food_consumption: int = 5
    relationships: list[list] = Field(default_factory=list)
    starting_conditions: StartingConditions
    strategic_context: str
    action_costs: dict[str, ActionCostConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_nations_and_relationships(self) -> ScenarioConfig:
        valid_names = {n.value for n in NationName}
        for key in self.nations:
            if key not in valid_names:
                raise ValueError(
                    f"Unknown nation '{key}'. Must be one of: {valid_names}"
                )
        for rel in self.relationships:
            if len(rel) != 3:
                raise ValueError(
                    f"Relationship must be [nation_a, nation_b, sentiment], got {rel}"
                )
            if rel[0] not in valid_names or rel[1] not in valid_names:
                raise ValueError(
                    f"Unknown nation in relationship {rel}. Must be one of: {valid_names}"
                )
        return self

    def to_starting_state(self) -> WorldState:
        """Construct the initial WorldState from scenario data."""
        nations = {}
        for key, cfg in self.nations.items():
            nation = NationName(key)
            nations[nation] = NationState(
                name=nation,
                resources=cfg.resources.model_copy(),
                traits=cfg.traits,
            )

        relationships = [
            Relationship(
                nation_a=NationName(rel[0]),
                nation_b=NationName(rel[1]),
                sentiment=rel[2],
            )
            for rel in self.relationships
        ]

        return WorldState(
            turn=1,
            max_turns=self.game.max_turns,
            nations=nations,
            relationships=relationships,
            reef_maru_status=self.starting_conditions.reef_maru_status,
            active_effects=list(self.starting_conditions.active_effects),
            strait_open=self.starting_conditions.strait_open,
        )

    @cached_property
    def _action_costs(self) -> dict[StandardActionType, ActionCost]:
        """Convert YAML action costs to the ActionCost dict used by rules.py."""
        result: dict[StandardActionType, ActionCost] = {}
        for key, cfg in self.action_costs.items():
            action_type = StandardActionType(key)
            result[action_type] = ActionCost(
                actor=dict(cfg.actor),
                target=dict(cfg.target) if cfg.target else {},
                requires_strait=cfg.requires_strait,
            )
        return result

    def get_action_costs(self) -> dict[StandardActionType, ActionCost]:
        """Get the action cost registry for the rule engine."""
        return self._action_costs

    def render_economic_rules(self) -> str:
        """Generate the ECONOMIC_RULES text block from numeric data."""
        lines = ["Each turn, the following automatic economic adjustments occur:", ""]

        # Treasury income
        lines.append("Treasury income (if trade routes are functional):")
        for key, cfg in self.nations.items():
            note = ""
            if cfg.economy.requires_strait_for_income:
                if key == "naru":
                    note = " (toll revenue from strait shipping)"
                else:
                    note = " (requires strait access)"
            else:
                if key == "tauma":
                    note = " (fishing economy)"
            lines.append(f"- {key.capitalize()}: +{cfg.economy.treasury_income}{note}")

        # Food
        lines.append("")
        lines.append("Food production:")
        for key, cfg in self.nations.items():
            lines.append(f"- {key.capitalize()}: +{cfg.economy.food_production}")

        lines.append("")
        lines.append(f"Food consumption: -{self.food_consumption} per turn for all nations.")

        # Strait blockade
        strait_nations = [
            k.capitalize()
            for k, c in self.nations.items()
            if c.economy.requires_strait_for_income
        ]
        if strait_nations:
            lines.append("")
            lines.append("If the Naru Strait is blockaded:")
            for name in strait_nations:
                lines.append(f"- {name} loses trade income")

        # Thresholds
        lines.append("")
        lines.append("Critical thresholds:")
        lines.append("- Food below 20: domestic unrest, -5 Support per turn")
        lines.append("- Food below 10: crisis, -10 Support per turn, risk of government collapse")
        lines.append(
            f"- Support below {self.game.instability_threshold}: "
            f"government instability, erratic behavior"
        )

        return "\n".join(lines)

    def render_action_menu(self) -> str:
        """Generate the ACTION_MENU text block from action costs."""
        # Group actions by category using StandardActionType membership
        categories: dict[str, list[str]] = {
            "MILITARY": [],
            "ECONOMIC": [],
            "DIPLOMATIC": [],
            "DOMESTIC": [],
        }

        _action_categories = {
            "naval_patrol": "MILITARY",
            "establish_base": "MILITARY",
            "naval_blockade": "MILITARY",
            "defensive_posture": "MILITARY",
            "trade_sanctions": "ECONOMIC",
            "invest_infrastructure": "ECONOMIC",
            "economic_aid": "ECONOMIC",
            "sovereignty_declaration": "DIPLOMATIC",
            "appeal_international": "DIPLOMATIC",
            "espionage": "DIPLOMATIC",
            "ration_food": "DOMESTIC",
            "propaganda": "DOMESTIC",
            "emergency_food_imports": "DOMESTIC",
        }

        _action_labels = {
            "naval_patrol": "Deploy naval patrol to Reef Maru",
            "establish_base": "Establish military base on Reef Maru",
            "naval_blockade": "Naval blockade of strait or port",
            "defensive_posture": "Defensive posture (fortify home waters)",
            "trade_sanctions": "Impose trade sanctions",
            "invest_infrastructure": "Invest in infrastructure",
            "economic_aid": "Economic aid to another nation",
            "sovereignty_declaration": "Public declaration of sovereignty over Reef Maru",
            "appeal_international": "Appeal to international community",
            "espionage": "Espionage",
            "ration_food": "Ration food supplies",
            "propaganda": "Propaganda campaign",
            "emergency_food_imports": "Emergency food imports",
        }

        for key, cfg in self.action_costs.items():
            category = _action_categories.get(key, "OTHER")
            label = _action_labels.get(key, key.replace("_", " ").title())
            parts = []
            for resource, delta in cfg.actor.items():
                parts.append(f"{delta:+d} {resource.capitalize()}")
            if cfg.target:
                for resource, delta in cfg.target.items():
                    parts.append(f"{delta:+d} target's {resource.capitalize()}")
            cost_str = ", ".join(parts) if parts else "variable"
            if cfg.requires_strait:
                cost_str += " (if trade routes open)"
            line = f"- {label}: {cost_str}"
            if category in categories:
                categories[category].append(line)

        lines = ["Common actions with approximate resource costs:", ""]
        for cat, items in categories.items():
            if items:
                lines.append(f"{cat}:")
                lines.extend(items)
                lines.append("")

        lines.append("Nations can attempt any plausible action — this menu is non-exhaustive.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_scenario(name: str) -> ScenarioConfig:
    """Load a scenario YAML file by name.

    Looks for ``scenarios/{name}.yaml`` relative to the project root.
    """
    path = _PROJECT_ROOT / "scenarios" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Scenario file not found: {path}\n"
            f"Available scenarios: {[p.stem for p in (_PROJECT_ROOT / 'scenarios').glob('*.yaml')]}"
        )
    with open(path) as f:
        data = yaml.safe_load(f)
    return ScenarioConfig.model_validate(data)
