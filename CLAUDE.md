# CLAUDE.md / Agents.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

IslandSim is a multi-agent tabletop exercise simulator where AI agents represent three island-nations (Naru, Veldara, Tauma) negotiating over a disputed resource discovery. A Facilitator agent acts as GM, resolving actions and injecting events. The game runs turn-based (configurable turns) with a resource system (Military, Treasury, Food, Public Support on 0–100 scales). Scenarios are defined in YAML files. See README.md for full game rules and world design.

## Development Environment

- Python 3.13, managed with `uv`
- Run all Python commands via `uv run` (e.g., `uv run python`, `uv run pytest`, `uv run jupyter`)
- Install dependencies: `uv sync`
- Run the game: `uv run python run_game.py [num_turns] [--scenario name]`
- **Testing**: Use 1 turn when verifying game runs (turns are slow due to LLM calls)
- Environment variables required in `.env`: `OPENROUTER_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`

## Key Dependencies

- **pydantic-ai**: Agent framework — used for country agents, facilitator, and summary agents
- **openrouter**: LLM access (models configured in `config.yaml` at project root)
- **langfuse**: Observability/tracing — agents instrumented via `Agent.instrument_all()` in `run_game.py`, game functions decorated with `@observe`
- **pydantic**: Data models for world state, actions, and turn resolution (all in `islandsim/models.py`)
- **pyyaml**: YAML loading for scenario and operational config files
- **textual**: TUI framework for the `--play` human-player interface (briefing / waiting / resolution / summary screens)

## Project Structure

- `run_game.py` — CLI entrypoint, loads env/instrumentation, runs the async game loop, saves structured game log to `logs/`. Supports `--play <nation>` to launch the human-player TUI.
- `scenarios/` — YAML scenario files defining world state, nation profiles, economics, and action costs
  - `reef_maru.yaml` — Default scenario (Reef Maru crisis in the Kalani Archipelago)
  - `south_china_sea.yaml` — Variant scenario (Jade Shoal standoff)
- `config.yaml` — Operational config (model selection, retries, default turns). Optional — defaults used if missing.
- `islandsim/models.py` — Pydantic models: `WorldState`, `NationState`, `Resources`, `TurnActions`, `Action`, `StandardActionType`, `TurnResolution`, `GameSummary`, `TurnRecord`, `GameLog`, etc.
- `islandsim/scenario.py` — Scenario config Pydantic models (`ScenarioConfig`, `NationConfig`, etc.), YAML loader (`load_scenario()`), and auto-generated prompt text (`render_economic_rules()`, `render_action_menu()`)
- `islandsim/settings.py` — Operational config model (`OperationalConfig`) and loader (`load_settings()`)
- `islandsim/agents.py` — Agent factory (`create_agents()`), `NationContext`/`FacilitatorContext` dataclasses
- `islandsim/game.py` — AI-only game loop: `run_game()` orchestrates turns, `collect_actions()` runs country agents concurrently, applies rule engine, `resolve_turn()` calls facilitator, validates output, `generate_summary()` produces end-game assessment. When `human_nation` is set, `run_game` dispatches to `islandsim.tui.run_game_tui` instead. Returns both `GameSummary` and a structured `GameLog`.
- `islandsim/tui.py` — Textual TUI for the human player. A long-lived `GameApp` drives the whole session, rotating screens (Briefing → Waiting → Resolution → Summary) via `switch_screen`. The game loop runs as a textual worker inside the app (so `active_app` is set in its context); AI country agents run as separate `asyncio.create_task`s in the background during the briefing so their failures cannot cancel the human's briefing future. Modals (`ActionDetailModal`, `CustomActionModal`, `ReasoningModal`) use callback-style `push_screen` (not `push_screen_wait`, which requires a worker context).
- `islandsim/rules.py` — Rule engine: `apply_economic_adjustments()` for deterministic per-turn income/food/penalties, `apply_action_costs()` for standard action costs (keyed off `Action.action_type`), `apply_changes()` to mechanically apply the facilitator's declarative `list[StateChange]` with clamping and audit logging
- `islandsim/prompts.py` — System prompt builders (`build_country_system_prompt`, `build_facilitator_system_prompt`) and per-turn prompt builders (`build_country_prompt`, `build_facilitator_prompt`, `build_summary_prompt`)
- `logs/` — Structured JSON game logs (gitignored), one file per run named `islandsim_<timestamp>.json`
- `test_pydantic.ipynb` — Early demo notebook (pydantic-ai + langfuse integration)

## Architecture

The game loop (`run_game`) loads a scenario YAML and operational config, creates agents via a factory function, then each turn: (1) runs all 3 country agents concurrently via `asyncio.gather`, each returning structured `TurnActions`, (2) the rule engine applies deterministic per-turn economic adjustments and pre-deducts costs for standard actions (identified by `Action.action_type`, a `StandardActionType` enum set by the country agents), (3) passes the adjusted state and all actions to the facilitator agent which returns a `TurnResolution` carrying a `list[StateChange]` (typed, discriminated-union mutations with a `reason` string each) plus narrative and private intel — the facilitator is told what costs are pre-applied and only emits changes for unmatched/custom actions and second-order effects, (4) `apply_changes()` mechanically applies each `StateChange` to the post-rule-engine state with clamping, writing `TurnRecord.final_state`, (5) distributes private intel and tracks event injection timing. After all turns, a summary agent generates a `GameSummary`.

All agent outputs use pydantic-ai's structured output — agents return typed Pydantic models, not free text. Country agents see their own resources, public info about others, relationships, history, and any private intel they've accumulated. Country agents classify their own actions using the `StandardActionType` enum (or `None` for creative/custom actions). The facilitator sees everything including secret actions.

## Human-player TUI

`uv run python run_game.py --play <naru|veldara|tauma>` launches the Textual TUI. Flow per turn:

1. **BriefingScreen** — state panels (your resources, other nations, relationships, world status, history/intel tabs) + action builder (category-filtered list, queued-actions list, submit). Selecting an action opens `ActionDetailModal` (visibility/target/description); custom actions open `CustomActionModal`. Submit pops `ReasoningModal` then signals the app.
2. **WaitingScreen** — `LoadingIndicator` + status text shown while AI country agents finish and the facilitator resolves.
3. **ResolutionScreen** — narrative, optional world event, resource delta table, and new intel. Continue advances to the next turn.
4. **SummaryScreen** — final `GameSummary` after the last turn.

Constraints / gotchas worth remembering:

- Do **not** use `textual.widgets.Header` in any screen — textual 8.2's `Header` has a reactive-title race (uncaught `NoMatches` on `HeaderTitle`) that bubbles up and cancels the game-loop worker. Use an inline `Static` title bar instead.
- `push_screen_wait` only works inside a textual worker; the per-screen event handlers that open modals use callback-style `push_screen(modal, callback)`.
- The game loop runs via `self.run_worker(self._game_loop())` in `on_mount` so it inherits the app's context. AI country agents are spawned with `asyncio.create_task` (not `asyncio.gather` with the briefing) so an AI failure can never cancel the human's briefing future.

## Configuration

**Scenario files** (`scenarios/*.yaml`): Define the game world — nation profiles, starting resources, economic parameters, relationships, action costs, and narrative context. Use `--scenario <name>` to select.

**Operational config** (`config.yaml`): Controls how the game runs — model selection, retries, default turn count. Edit this to swap models for regression testing without touching scenario data. Falls back to defaults if the file is missing.

## Game Logging

Each game run produces a structured JSON log (`GameLog` model) saved to `logs/islandsim_<timestamp>.json`. The log captures the initial world state, every turn's actions and facilitator resolution (via `TurnRecord`), and the final `GameSummary`. This provides a complete replay-friendly record of the game.
