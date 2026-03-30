from __future__ import annotations

import asyncio
import datetime
import os
from typing import Callable

if os.environ.get("LANGFUSE_SECRET_KEY"):
    from langfuse import observe
else:

    def observe(name: str = "") -> Callable:
        """No-op replacement for langfuse @observe when telemetry is disabled."""

        def decorator(func: Callable) -> Callable:
            return func

        return decorator

from islandsim.agents import (
    COUNTRY_AGENTS,
    FacilitatorContext,
    NationContext,
    facilitator_agent,
    summary_agent,
)
from islandsim.config import STARTING_STATE
from islandsim.models import (
    GameLog,
    GameSummary,
    NationName,
    TurnActions,
    TurnRecord,
    TurnResolution,
    WorldState,
)
from islandsim.prompts import build_country_prompt, build_facilitator_prompt, build_summary_prompt
from islandsim.rules import apply_action_costs, apply_economic_adjustments, validate_resolution


@observe(name="country_turn")
async def run_country_agent(
    nation: NationName,
    world_state: WorldState,
    history: list[str],
    private_intel: list[str],
) -> TurnActions:
    """Run a single country agent for one turn."""
    agent = COUNTRY_AGENTS[nation]
    ctx = NationContext(
        nation=nation,
        world_state=world_state,
        own_private_intel=private_intel,
        history=history,
    )
    prompt = build_country_prompt(ctx)
    result = await agent.run(prompt)
    return result.output


@observe(name="collect_actions")
async def collect_actions(
    world_state: WorldState,
    history: list[str],
    private_intel: dict[NationName, list[str]],
) -> dict[NationName, TurnActions]:
    """Run all three country agents concurrently."""
    results = await asyncio.gather(
        run_country_agent(NationName.NARU, world_state, history, private_intel[NationName.NARU]),
        run_country_agent(NationName.VELDARA, world_state, history, private_intel[NationName.VELDARA]),
        run_country_agent(NationName.TAUMA, world_state, history, private_intel[NationName.TAUMA]),
    )
    return {r.nation: r for r in results}


@observe(name="resolve_turn")
async def resolve_turn(
    world_state: WorldState,
    all_actions: dict[NationName, TurnActions],
    history: list[str],
    turns_since_last_event: int,
    econ_changes: dict[NationName, dict[str, int]] | None = None,
    applied_costs: list | None = None,
    unmatched_actions: list | None = None,
) -> TurnResolution:
    """Have the facilitator resolve all actions and return updated state."""
    ctx = FacilitatorContext(
        world_state=world_state,
        all_actions=all_actions,
        history=history,
        turns_since_last_event=turns_since_last_event,
        econ_changes=econ_changes or {},
        applied_costs=applied_costs or [],
        unmatched_actions=unmatched_actions or [],
    )
    prompt = build_facilitator_prompt(ctx)
    result = await facilitator_agent.run(prompt)
    return result.output


@observe(name="generate_summary")
async def generate_summary(
    world_state: WorldState,
    history: list[str],
) -> GameSummary:
    """Generate the final game summary."""
    prompt = build_summary_prompt(world_state, history)
    result = await summary_agent.run(prompt)
    return result.output


@observe(name="islandsim_game")
async def run_game(num_turns: int = 4) -> tuple[GameSummary, GameLog]:
    """Run the full game loop."""
    state = STARTING_STATE.model_copy(deep=True)
    state.max_turns = num_turns
    initial_state = state.model_copy(deep=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    history: list[str] = []
    private_intel: dict[NationName, list[str]] = {n: [] for n in NationName}
    turns_since_event = 0
    turn_records: list[TurnRecord] = []

    for turn in range(1, num_turns + 1):
        state.turn = turn
        print(f"\n{'='*60}")
        print(f"  TURN {turn} of {num_turns}")
        print(f"{'='*60}")

        # Phase 1: Country agents submit actions
        print("\nCountry agents deliberating...")
        all_actions = await collect_actions(state, history, private_intel)

        for nation_name, turn_actions in all_actions.items():
            print(f"\n  {nation_name.value.upper()} actions:")
            for i, action in enumerate(turn_actions.actions, 1):
                vis = action.visibility.value.upper()
                print(f"    {i}. [{vis}] {action.description}")

        # Phase 1.5: Rule engine pre-processing
        adjusted_state, econ_changes = apply_economic_adjustments(state)
        engine_state, applied_costs, unmatched = apply_action_costs(
            adjusted_state, all_actions
        )

        print("\n  RULE ENGINE:")
        for nation in NationName:
            deltas = econ_changes.get(nation, {})
            if deltas:
                parts = [f"{k} {v:+d}" for k, v in deltas.items()]
                print(f"    {nation.value.upper()} econ: {', '.join(parts)}")
        for ac in applied_costs:
            changes_parts = []
            for n, d in ac.resource_changes.items():
                for k, v in d.items():
                    changes_parts.append(f"{k} {v:+d}")
            print(
                f"    {ac.nation.value.upper()} action [{ac.action_type.value}]: "
                f"{', '.join(changes_parts) or 'no change'}"
            )
        if unmatched:
            for nation, action in unmatched:
                print(f"    {nation.value.upper()} unmatched: {action.description}")

        # Phase 2: Facilitator resolves
        print("\nFacilitator resolving...")
        resolution = await resolve_turn(
            engine_state, all_actions, history, turns_since_event,
            econ_changes, applied_costs, unmatched,
        )

        # Phase 2.5: Validate facilitator output
        resolution = validate_resolution(engine_state, resolution, applied_costs)

        # Record turn data
        turn_records.append(TurnRecord(turn=turn, actions=all_actions, resolution=resolution))

        # Phase 3: Update state and history
        state = resolution.updated_state
        history.append(f"Turn {turn}: {resolution.narrative}")

        # Distribute private intel
        for nation in NationName:
            nation_intel = resolution.private_intel.get(nation, [])
            if nation_intel:
                private_intel[nation].extend(nation_intel)

        # Track event injection
        if resolution.event_injected:
            turns_since_event = 0
            print(f"\n  EVENT: {resolution.event_injected}")
        else:
            turns_since_event += 1

        # Print turn narrative
        print(f"\n  NARRATIVE: {resolution.narrative}")

        # Print resource summary
        print(f"\n  RESOURCES:")
        for name, ns in state.nations.items():
            r = ns.resources
            print(
                f"    {name.value.upper()}: "
                f"M={r.military} T={r.treasury} F={r.food} S={r.support}"
            )

    # Final summary
    print(f"\n{'='*60}")
    print("  GAME OVER — Generating summary...")
    print(f"{'='*60}")

    summary = await generate_summary(state, history)

    print(f"\n{summary.narrative}")
    print(f"\nReef Maru: {summary.reef_maru_outcome}")
    for nation, assessment in summary.nation_assessments.items():
        print(f"\n  {nation.value.upper()}: {assessment}")

    game_log = GameLog(
        timestamp=timestamp,
        num_turns=num_turns,
        initial_state=initial_state,
        turns=turn_records,
        summary=summary,
    )
    return summary, game_log
