"""Rule engine for deterministic resource adjudication.

Applies per-turn economic adjustments and standard action costs before the
facilitator LLM, and validates facilitator output afterward.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from islandsim.models import (
    Action,
    NationName,
    StandardActionType,
    TurnActions,
    TurnResolution,
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
# Facilitator output validation
# ---------------------------------------------------------------------------


def validate_resolution(
    post_engine_state: WorldState,
    resolution: TurnResolution,
    applied_costs: list[AppliedCost],
) -> TurnResolution:
    """Validate and correct the facilitator's resolution if needed.

    Ensures pre-applied costs are respected and resources stay in bounds.
    """
    updated = resolution.updated_state
    warnings: list[str] = []

    # Build expected minimum changes per nation from pre-applied costs.
    expected_by_nation: dict[NationName, dict[str, int]] = {}
    for ac in applied_costs:
        for nation, deltas in ac.resource_changes.items():
            if nation not in expected_by_nation:
                expected_by_nation[nation] = {}
            for field, delta in deltas.items():
                expected_by_nation[nation][field] = (
                    expected_by_nation[nation].get(field, 0) + delta
                )

    for nation in NationName:
        engine_resources = post_engine_state.nations[nation].resources
        fac_resources = updated.nations[nation].resources

        for field in ("military", "treasury", "food", "support"):
            engine_val = getattr(engine_resources, field)
            fac_val = getattr(fac_resources, field)

            # Clamp to bounds (safety net)
            clamped = _clamp(fac_val)
            if clamped != fac_val:
                warnings.append(
                    f"{nation.value} {field}: facilitator returned {fac_val}, "
                    f"clamped to {clamped}"
                )
                setattr(fac_resources, field, clamped)
                fac_val = clamped

            # Check if facilitator undid pre-applied costs.
            # The facilitator may legitimately reverse a pre-applied cost
            # (e.g., rejecting an action due to game state), so we warn
            # but do not override.
            expected = expected_by_nation.get(nation, {})
            if field in expected:
                pre_applied_delta = expected[field]
                fac_delta = fac_val - engine_val
                if pre_applied_delta < 0 and fac_delta > 0:
                    warnings.append(
                        f"{nation.value} {field}: rule engine applied "
                        f"{pre_applied_delta}, facilitator reversed {fac_delta} "
                        f"(may be a legitimate override)"
                    )

    if warnings:
        for w in warnings:
            print(f"  [RULE ENGINE WARNING] {w}")

    return resolution
