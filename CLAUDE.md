# CLAUDE.md / Agents.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

IslandSim is a multi-agent tabletop exercise simulator where AI agents represent three island-nations (Naru, Veldara, Tauma) negotiating over a disputed resource discovery. A Facilitator agent acts as GM, resolving actions and injecting events. The game runs turn-based (configurable turns) with a resource system (Military, Treasury, Food, Public Support on 0–100 scales). Scenarios are defined in YAML files. See README.md for full game rules and world design.

## Development Environment

- Python 3.13, managed with `uv`
- Run all Python commands via `uv run` (e.g., `uv run python`, `uv run pytest`, `uv run jupyter`)
- Install dependencies: `uv sync`
- Run the game: `uv run python run_game.py [num_turns] [--scenario name]`
- Environment variables required in `.env`: `OPENROUTER_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`

## Key Dependencies

- **pydantic-ai**: Agent framework — used for country agents, facilitator, and summary agents
- **openrouter**: LLM access (models configured in `config.yaml` at project root)
- **langfuse**: Observability/tracing — agents instrumented via `Agent.instrument_all()` in `run_game.py`, game functions decorated with `@observe`
- **pydantic**: Data models for world state, actions, and turn resolution (all in `islandsim/models.py`)
- **pyyaml**: YAML loading for scenario and operational config files

## Project Structure

- `run_game.py` — CLI entrypoint, loads env/instrumentation, runs the async game loop, saves structured game log to `logs/`
- `scenarios/` — YAML scenario files defining world state, nation profiles, economics, and action costs
  - `reef_maru.yaml` — Default scenario (Reef Maru crisis in the Kalani Archipelago)
  - `south_china_sea.yaml` — Variant scenario (Jade Shoal standoff)
- `config.yaml` — Operational config (model selection, retries, default turns). Optional — defaults used if missing.
- `islandsim/models.py` — Pydantic models: `WorldState`, `NationState`, `Resources`, `TurnActions`, `Action`, `StandardActionType`, `TurnResolution`, `GameSummary`, `TurnRecord`, `GameLog`, etc.
- `islandsim/scenario.py` — Scenario config Pydantic models (`ScenarioConfig`, `NationConfig`, etc.), YAML loader (`load_scenario()`), and auto-generated prompt text (`render_economic_rules()`, `render_action_menu()`)
- `islandsim/settings.py` — Operational config model (`OperationalConfig`) and loader (`load_settings()`)
- `islandsim/agents.py` — Agent factory (`create_agents()`), `NationContext`/`FacilitatorContext` dataclasses
- `islandsim/game.py` — Game loop: `run_game()` orchestrates turns, `collect_actions()` runs country agents concurrently, applies rule engine, `resolve_turn()` calls facilitator, validates output, `generate_summary()` produces end-game assessment. Returns both `GameSummary` and a structured `GameLog` capturing every turn's actions and resolutions
- `islandsim/rules.py` — Rule engine: `apply_economic_adjustments()` for deterministic per-turn income/food/penalties, `apply_action_costs()` for standard action costs (keyed off `Action.action_type`), `validate_resolution()` to enforce facilitator compliance
- `islandsim/prompts.py` — System prompt builders (`build_country_system_prompt`, `build_facilitator_system_prompt`) and per-turn prompt builders (`build_country_prompt`, `build_facilitator_prompt`, `build_summary_prompt`)
- `logs/` — Structured JSON game logs (gitignored), one file per run named `islandsim_<timestamp>.json`
- `test_pydantic.ipynb` — Early demo notebook (pydantic-ai + langfuse integration)

## Architecture

The game loop (`run_game`) loads a scenario YAML and operational config, creates agents via a factory function, then each turn: (1) runs all 3 country agents concurrently via `asyncio.gather`, each returning structured `TurnActions`, (2) the rule engine applies deterministic per-turn economic adjustments and pre-deducts costs for standard actions (identified by `Action.action_type`, a `StandardActionType` enum set by the country agents), (3) passes the adjusted state and all actions to the facilitator agent which returns a `TurnResolution` with updated `WorldState`, narrative, and private intel — the facilitator is told what costs are pre-applied and only resolves unmatched/custom actions, (4) the rule engine validates the facilitator's output to ensure pre-applied costs weren't undone, (5) distributes private intel and tracks event injection timing. After all turns, a summary agent generates a `GameSummary`.

All agent outputs use pydantic-ai's structured output — agents return typed Pydantic models, not free text. Country agents see their own resources, public info about others, relationships, history, and any private intel they've accumulated. Country agents classify their own actions using the `StandardActionType` enum (or `None` for creative/custom actions). The facilitator sees everything including secret actions.

## Configuration

**Scenario files** (`scenarios/*.yaml`): Define the game world — nation profiles, starting resources, economic parameters, relationships, action costs, and narrative context. Use `--scenario <name>` to select.

**Operational config** (`config.yaml`): Controls how the game runs — model selection, retries, default turn count. Edit this to swap models for regression testing without touching scenario data. Falls back to defaults if the file is missing.

## Game Logging

Each game run produces a structured JSON log (`GameLog` model) saved to `logs/islandsim_<timestamp>.json`. The log captures the initial world state, every turn's actions and facilitator resolution (via `TurnRecord`), and the final `GameSummary`. This provides a complete replay-friendly record of the game.
