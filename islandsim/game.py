from __future__ import annotations

import asyncio
import datetime
import os
import random
from typing import Callable

from pydantic_ai import Agent

from islandsim.settings import load_settings as _load_settings

_settings = _load_settings()

if _settings.langfuse and os.environ.get("LANGFUSE_SECRET_KEY"):
    from langfuse import observe
else:

    def observe(name: str = "") -> Callable:
        """No-op replacement for langfuse @observe when telemetry is disabled."""

        def decorator(func: Callable) -> Callable:
            return func

        return decorator

from islandsim.agents import (
    FacilitatorContext,
    FacilitatorDeps,
    NationContext,
    create_agents,
)
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
from islandsim.rules import apply_action_costs, apply_changes, apply_economic_adjustments
from islandsim.scenario import ScenarioConfig, load_scenario
from islandsim.settings import OperationalConfig, load_settings


@observe(name="country_turn")
async def run_country_agent(
    nation: NationName,
    world_state: WorldState,
    history: list[str],
    private_intel: list[str],
    agent: Agent[None, TurnActions],
) -> TurnActions:
    """Run a single country agent for one turn."""
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
    country_agents: dict[NationName, Agent[None, TurnActions]],
) -> dict[NationName, TurnActions]:
    """Run all three country agents concurrently (AI-only path)."""
    tasks = [
        run_country_agent(
            nation, world_state, history, private_intel[nation], country_agents[nation],
        )
        for nation in NationName
    ]
    results = await asyncio.gather(*tasks)
    return {r.nation: r for r in results}


@observe(name="resolve_turn")
async def resolve_turn(
    world_state: WorldState,
    all_actions: dict[NationName, TurnActions],
    history: list[str],
    turns_since_last_event: int,
    facilitator: Agent[FacilitatorDeps, TurnResolution],
    econ_changes: dict[NationName, dict[str, int]] | None = None,
    applied_costs: list | None = None,
    unmatched_actions: list | None = None,
) -> TurnResolution:
    """Have the facilitator resolve all actions and return updated state.

    Per-turn ``FacilitatorDeps`` carries the post-rule-engine state to
    the ``skill_roll`` tool and collects a roll log that is attached to
    the returned resolution.
    """
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
    deps = FacilitatorDeps(world_state=world_state)
    result = await facilitator.run(prompt, deps=deps)
    resolution = result.output
    resolution.skill_rolls = list(deps.roll_log)
    return resolution


@observe(name="generate_summary")
async def generate_summary(
    world_state: WorldState,
    history: list[str],
    summary_agent: Agent[None, GameSummary],
) -> GameSummary:
    """Generate the final game summary."""
    prompt = build_summary_prompt(world_state, history)
    result = await summary_agent.run(prompt)
    return result.output


@observe(name="islandsim_game")
async def run_game(
    scenario_name: str = "reef_maru",
    num_turns: int | None = None,
    human_nation: NationName | None = None,
    seed: int | None = None,
) -> tuple[GameSummary, GameLog]:
    """Run the full game loop.

    When *human_nation* is set, the TUI-driven path in
    :func:`islandsim.tui.run_game_tui` is used.  Otherwise this is the
    AI-only path.
    """
    if human_nation is not None:
        from islandsim.tui import run_game_tui

        return await run_game_tui(scenario_name, num_turns, human_nation, seed=seed)

    rng = random.Random(seed) if seed is not None else None
    scenario = load_scenario(scenario_name)
    settings = load_settings()
    country_agents, facilitator, summary_agent_inst = create_agents(scenario, settings, rng=rng)

    state = scenario.to_starting_state()
    turns = num_turns if num_turns is not None else settings.default_turns
    state.max_turns = turns
    initial_state = state.model_copy(deep=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    history: list[str] = []
    private_intel: dict[NationName, list[str]] = {n: [] for n in NationName}
    turns_since_event = 0
    turn_records: list[TurnRecord] = []

    # Line-UI / AI-only path below.  The TUI path dispatched to
    # run_game_tui() above and never reaches here.
    print(f"\nScenario: {scenario.meta.name}")
    print(f"Models: country={settings.models.country}, facilitator={settings.models.facilitator}")

    for turn in range(1, turns + 1):
        state.turn = turn
        print(f"\n{'='*60}")
        print(f"  TURN {turn} of {turns}")
        print(f"{'='*60}")

        # Phase 1: Country agents submit actions
        print("\nCountry agents deliberating...")
        all_actions = await collect_actions(
            state, history, private_intel, country_agents,
        )

        for nation_name, turn_actions in all_actions.items():
            print(f"\n  {nation_name.value.upper()} actions:")
            for i, action in enumerate(turn_actions.actions, 1):
                vis = action.visibility.value.upper()
                print(f"    {i}. [{vis}] {action.description}")

        # Phase 1.5: Rule engine pre-processing
        adjusted_state, econ_changes = apply_economic_adjustments(state, scenario)
        engine_state, applied_costs, unmatched = apply_action_costs(
            adjusted_state, all_actions, scenario,
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

        # Snapshot state before resolution for delta display
        prev_state = engine_state.model_copy(deep=True)

        # Phase 2: Facilitator resolves
        print("\nFacilitator resolving...")
        resolution = await resolve_turn(
            engine_state, all_actions, history, turns_since_event,
            facilitator, econ_changes, applied_costs, unmatched,
        )

        # Phase 2.5: Apply declarative state changes from the facilitator
        state, applied_changes, _change_warnings = apply_changes(
            engine_state, resolution.changes,
        )

        if applied_changes:
            print("\n  STATE CHANGES:")
            for ac in applied_changes:
                print(f"    {ac.effect} — {ac.change.reason}")

        turn_records.append(TurnRecord(
            turn=turn, actions=all_actions, resolution=resolution, final_state=state,
        ))

        history.append(f"Turn {turn}: {resolution.narrative}")

        for nation in NationName:
            nation_intel = resolution.private_intel.get(nation, [])
            if nation_intel:
                private_intel[nation].extend(nation_intel)

        if resolution.event_injected:
            turns_since_event = 0
            print(f"\n  EVENT: {resolution.event_injected}")
        else:
            turns_since_event += 1

        print(f"\n  NARRATIVE: {resolution.narrative}")
        print(f"\n  RESOURCES:")
        for name, ns in state.nations.items():
            r = ns.resources
            print(
                f"    {name.value.upper()}: "
                f"M={r.military} T={r.treasury} F={r.food} S={r.support}"
            )

    print(f"\n{'='*60}")
    print("  GAME OVER — Generating summary...")
    print(f"{'='*60}")

    summary = await generate_summary(state, history, summary_agent_inst)

    print(f"\n{summary.narrative}")
    print(f"\nReef Maru: {summary.reef_maru_outcome}")
    for nation, assessment in summary.nation_assessments.items():
        print(f"\n  {nation.value.upper()}: {assessment}")

    game_log = GameLog(
        timestamp=timestamp,
        num_turns=turns,
        initial_state=initial_state,
        turns=turn_records,
        summary=summary,
    )
    return summary, game_log
