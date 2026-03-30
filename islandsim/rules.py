"""Rule engine for deterministic resource adjudication.

Applies per-turn economic adjustments and standard action costs before the
facilitator LLM, and validates facilitator output afterward.
"""

from __future__ import annotations

import dataclasses

from islandsim.models import (
    Action,
    NationName,
    StandardActionType,
    TurnActions,
    TurnResolution,
    WorldState,
)

# ---------------------------------------------------------------------------
# Cost registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ActionCost:
    """Resource cost definition for a standard action."""

    actor: dict[str, int] = dataclasses.field(default_factory=dict)
    target: dict[str, int] = dataclasses.field(default_factory=dict)
    requires_strait: bool = False


ACTION_COSTS: dict[StandardActionType, ActionCost] = {
    StandardActionType.NAVAL_PATROL: ActionCost(
        actor={"military": -10, "treasury": -5},
    ),
    StandardActionType.ESTABLISH_BASE: ActionCost(
        actor={"military": -20, "treasury": -15},
    ),
    StandardActionType.NAVAL_BLOCKADE: ActionCost(
        actor={"military": -15},
    ),
    StandardActionType.DEFENSIVE_POSTURE: ActionCost(
        actor={"military": -5, "support": 5},
    ),
    StandardActionType.TRADE_SANCTIONS: ActionCost(
        actor={"treasury": -5},
    ),
    StandardActionType.INVEST_INFRASTRUCTURE: ActionCost(
        actor={"treasury": -15},
    ),
    StandardActionType.ECONOMIC_AID: ActionCost(
        actor={"treasury": -10},
        target={"support": 10},
    ),
    StandardActionType.SOVEREIGNTY_DECLARATION: ActionCost(
        actor={"support": 5},
    ),
    StandardActionType.APPEAL_INTERNATIONAL: ActionCost(
        actor={"support": 5},
    ),
    StandardActionType.ESPIONAGE: ActionCost(
        actor={"treasury": -5},
    ),
    StandardActionType.RATION_FOOD: ActionCost(
        actor={"support": -5},
    ),
    StandardActionType.PROPAGANDA: ActionCost(
        actor={"treasury": -5, "support": 10},
    ),
    StandardActionType.EMERGENCY_FOOD_IMPORTS: ActionCost(
        actor={"treasury": -15, "food": 15},
        requires_strait=True,
    ),
}

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

# Income per turn when trade routes are functional.
_TREASURY_INCOME: dict[NationName, int] = {
    NationName.NARU: 10,
    NationName.VELDARA: 8,
    NationName.TAUMA: 5,
}

# Nations whose treasury income requires the strait to be open.
_REQUIRES_STRAIT_FOR_INCOME: set[NationName] = {NationName.NARU, NationName.VELDARA}

# Food production per turn.
_FOOD_PRODUCTION: dict[NationName, int] = {
    NationName.NARU: 3,
    NationName.VELDARA: 8,
    NationName.TAUMA: 5,
}

_FOOD_CONSUMPTION = 5  # All nations consume this per turn.


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def apply_economic_adjustments(
    state: WorldState,
) -> tuple[WorldState, dict[NationName, dict[str, int]]]:
    """Apply deterministic per-turn income, food, and threshold penalties.

    Returns (new_state, changes_log) where changes_log maps each nation
    to the resource deltas that were applied.
    """
    state = state.model_copy(deep=True)
    changes: dict[NationName, dict[str, int]] = {}

    for nation in NationName:
        ns = state.nations[nation]
        deltas: dict[str, int] = {}

        # Treasury income
        income = _TREASURY_INCOME[nation]
        if not state.strait_open and nation in _REQUIRES_STRAIT_FOR_INCOME:
            income = 0
        if income:
            deltas["treasury"] = income
            ns.resources.treasury = _clamp(ns.resources.treasury + income)

        # Food production and consumption
        food_delta = _FOOD_PRODUCTION[nation] - _FOOD_CONSUMPTION
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
) -> tuple[WorldState, list[AppliedCost], list[tuple[NationName, Action]]]:
    """Apply resource costs for actions with a standard action_type.

    Actions with action_type=None are passed through as unmatched.
    Returns (new_state, applied_costs, unmatched_actions).
    """
    state = state.model_copy(deep=True)
    applied: list[AppliedCost] = []
    unmatched: list[tuple[NationName, Action]] = []

    for nation, turn_actions in all_actions.items():
        for action in turn_actions.actions:
            if action.action_type is None:
                unmatched.append((nation, action))
                continue

            cost_def = ACTION_COSTS[action.action_type]

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
            expected = expected_by_nation.get(nation, {})
            if field in expected:
                pre_applied_delta = expected[field]
                fac_delta = fac_val - engine_val
                # If we applied a cost (negative delta) but facilitator added
                # back more than we deducted, that's suspicious
                if pre_applied_delta < 0 and fac_delta > 0:
                    warnings.append(
                        f"{nation.value} {field}: rule engine applied "
                        f"{pre_applied_delta}, but facilitator added {fac_delta} "
                        f"back — overriding to engine value {engine_val}"
                    )
                    setattr(fac_resources, field, engine_val)

    if warnings:
        for w in warnings:
            print(f"  [RULE ENGINE WARNING] {w}")

    return resolution
