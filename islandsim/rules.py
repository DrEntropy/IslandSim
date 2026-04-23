"""Rule engine for deterministic resource adjudication.

Applies per-turn economic adjustments and standard action costs before the
facilitator LLM, and mechanically applies the facilitator's declarative
``list[StateChange]`` afterward (with clamping and audit logging).
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING

from islandsim.models import (
    Action,
    ActiveEffectAdd,
    ActiveEffectRemove,
    NationName,
    ReefMaruStatusChange,
    Relationship,
    RelationshipChange,
    ResourceChange,
    StandardActionType,
    StateChange,
    StraitChange,
    TurnActions,
    WorldState,
)

if TYPE_CHECKING:
    from islandsim.scenario import ScenarioConfig

# ---------------------------------------------------------------------------
# Cost registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ActionCost:
    """Resource cost definition for a standard action."""

    actor: dict[str, int] = dataclasses.field(default_factory=dict)
    target: dict[str, int] = dataclasses.field(default_factory=dict)
    requires_strait: bool = False


# ---------------------------------------------------------------------------
# Applied cost tracking
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AppliedCost:
    """Record of a standard action cost that was pre-applied."""

    nation: NationName
    action: Action
    action_type: StandardActionType
    resource_changes: dict[NationName, dict[str, int]]


# ---------------------------------------------------------------------------
# Per-turn economic adjustments
# ---------------------------------------------------------------------------


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def apply_economic_adjustments(
    state: WorldState,
    scenario: ScenarioConfig,
) -> tuple[WorldState, dict[NationName, dict[str, int]]]:
    """Apply deterministic per-turn income, food, and threshold penalties.

    Returns (new_state, changes_log) where changes_log maps each nation
    to the resource deltas that were applied.
    """
    state = state.model_copy(deep=True)
    changes: dict[NationName, dict[str, int]] = {}

    for nation in NationName:
        ns = state.nations[nation]
        nation_cfg = scenario.nations[nation.value]
        deltas: dict[str, int] = {}

        # Treasury income
        income = nation_cfg.economy.treasury_income
        if not state.strait_open and nation_cfg.economy.requires_strait_for_income:
            income = 0
        if income:
            deltas["treasury"] = income
            ns.resources.treasury = _clamp(ns.resources.treasury + income)

        # Food production and consumption
        food_delta = nation_cfg.economy.food_production - scenario.food_consumption
        if food_delta:
            deltas["food"] = food_delta
            ns.resources.food = _clamp(ns.resources.food + food_delta)

        # Threshold penalties (applied after food update)
        if ns.resources.food < 10:
            deltas["support"] = deltas.get("support", 0) - 10
            ns.resources.support = _clamp(ns.resources.support - 10)
        elif ns.resources.food < 20:
            deltas["support"] = deltas.get("support", 0) - 5
            ns.resources.support = _clamp(ns.resources.support - 5)

        changes[nation] = deltas

    return state, changes


# ---------------------------------------------------------------------------
# Standard action cost application
# ---------------------------------------------------------------------------


def apply_action_costs(
    state: WorldState,
    all_actions: dict[NationName, TurnActions],
    scenario: ScenarioConfig,
) -> tuple[WorldState, list[AppliedCost], list[tuple[NationName, Action]]]:
    """Apply resource costs for actions with a standard action_type.

    Actions with action_type=None are passed through as unmatched.
    Returns (new_state, applied_costs, unmatched_actions).
    """
    state = state.model_copy(deep=True)
    applied: list[AppliedCost] = []
    unmatched: list[tuple[NationName, Action]] = []
    action_costs = scenario.get_action_costs()

    for nation, turn_actions in all_actions.items():
        for action in turn_actions.actions:
            if action.action_type is None:
                unmatched.append((nation, action))
                continue

            cost_def = action_costs[action.action_type]

            # Check conditions
            if cost_def.requires_strait and not state.strait_open:
                unmatched.append((nation, action))
                continue

            resource_changes: dict[NationName, dict[str, int]] = {}

            # Apply actor costs
            if cost_def.actor:
                actor_deltas: dict[str, int] = {}
                resources = state.nations[nation].resources
                for field, delta in cost_def.actor.items():
                    current = getattr(resources, field)
                    new_val = _clamp(current + delta)
                    actual_delta = new_val - current
                    setattr(resources, field, new_val)
                    if actual_delta:
                        actor_deltas[field] = actual_delta
                if actor_deltas:
                    resource_changes[nation] = actor_deltas

            # Apply target costs
            if cost_def.target and action.target:
                target_deltas: dict[str, int] = {}
                target_resources = state.nations[action.target].resources
                for field, delta in cost_def.target.items():
                    current = getattr(target_resources, field)
                    new_val = _clamp(current + delta)
                    actual_delta = new_val - current
                    setattr(target_resources, field, new_val)
                    if actual_delta:
                        target_deltas[field] = actual_delta
                if target_deltas:
                    resource_changes[action.target] = target_deltas

            applied.append(AppliedCost(
                nation=nation,
                action=action,
                action_type=action.action_type,
                resource_changes=resource_changes,
            ))

    return state, applied, unmatched


# ---------------------------------------------------------------------------
# Stochastic skill rolls
# ---------------------------------------------------------------------------


_DEFAULT_RNG = random.Random()


@dataclasses.dataclass
class SkillRollOutcome:
    """Result of a single opposed skill roll."""

    attacker_skill: int
    defender_skill: int
    difficulty: int
    roll: int
    margin: int
    success: bool


def skill_roll(
    attacker_skill: int,
    defender_skill: int,
    difficulty: int = 0,
    rng: random.Random | None = None,
) -> SkillRollOutcome:
    """Opposed skill check with uniform noise.

    margin = attacker_skill - defender_skill - difficulty + U(-30, +30)
    success when margin >= 0.
    """
    r = rng if rng is not None else _DEFAULT_RNG
    noise = r.randint(-30, 30)
    margin = attacker_skill - defender_skill - difficulty + noise
    return SkillRollOutcome(
        attacker_skill=attacker_skill,
        defender_skill=defender_skill,
        difficulty=difficulty,
        roll=noise,
        margin=margin,
        success=margin >= 0,
    )


# ---------------------------------------------------------------------------
# Declarative state-change application
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AppliedChange:
    """Record of a StateChange that was applied, with its final (clamped) effect."""

    change: StateChange
    effect: str
    """Human-readable summary of what actually changed, after clamping."""


def _find_relationship(state: WorldState, a: NationName, b: NationName) -> Relationship | None:
    """Relationships are unordered pairs; look up regardless of order."""
    for rel in state.relationships:
        if {rel.nation_a, rel.nation_b} == {a, b}:
            return rel
    return None


def apply_changes(
    state: WorldState,
    changes: list[StateChange],
) -> tuple[WorldState, list[AppliedChange], list[str]]:
    """Apply the facilitator's declarative state changes.

    Returns (new_state, applied, warnings). Each change produces at most one
    AppliedChange; rejected changes go into warnings. All numeric fields are
    clamped. WorldState fields not mentioned by any change (turn, max_turns,
    nations dict keys, intel_skill, etc.) are left untouched by construction.
    """
    state = state.model_copy(deep=True)
    applied: list[AppliedChange] = []
    warnings: list[str] = []

    for change in changes:
        match change:
            case ResourceChange():
                resources = state.nations[change.nation].resources
                current = getattr(resources, change.field)
                new_val = _clamp(current + change.delta)
                setattr(resources, change.field, new_val)
                actual = new_val - current
                applied.append(AppliedChange(
                    change=change,
                    effect=f"{change.nation.value}.{change.field} {actual:+d} "
                           f"({current} → {new_val})",
                ))

            case RelationshipChange():
                rel = _find_relationship(state, change.nation_a, change.nation_b)
                if rel is None:
                    warnings.append(
                        f"relationship: no pair {change.nation_a.value}/"
                        f"{change.nation_b.value}"
                    )
                    continue
                current = rel.sentiment
                rel.sentiment = max(-100, min(100, current + change.delta))
                actual = rel.sentiment - current
                applied.append(AppliedChange(
                    change=change,
                    effect=f"{rel.nation_a.value}↔{rel.nation_b.value} sentiment "
                           f"{actual:+d} ({current} → {rel.sentiment})",
                ))

            case StraitChange():
                prev = state.strait_open
                state.strait_open = change.open
                applied.append(AppliedChange(
                    change=change,
                    effect=f"strait_open {prev} → {state.strait_open}",
                ))

            case ActiveEffectAdd():
                if change.effect not in state.active_effects:
                    state.active_effects.append(change.effect)
                applied.append(AppliedChange(
                    change=change, effect=f"+effect: {change.effect}",
                ))

            case ActiveEffectRemove():
                if change.effect in state.active_effects:
                    state.active_effects.remove(change.effect)
                    applied.append(AppliedChange(
                        change=change, effect=f"-effect: {change.effect}",
                    ))
                else:
                    warnings.append(
                        f"effect_remove: no such active effect '{change.effect}'"
                    )

            case ReefMaruStatusChange():
                prev = state.reef_maru_status
                state.reef_maru_status = change.new_status
                applied.append(AppliedChange(
                    change=change,
                    effect=f"reef_maru_status: '{prev}' → '{state.reef_maru_status}'",
                ))

    if warnings:
        for w in warnings:
            print(f"  [RULE ENGINE WARNING] {w}")

    return state, applied, warnings
