# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IslandSim is a multi-agent tabletop exercise simulator where AI agents represent three island-nations (Naru, Veldara, Tauma) negotiating over a disputed resource discovery (Reef Maru). A Facilitator agent acts as GM, resolving actions and injecting events. The game runs turn-based (default 4 turns, configurable) with a resource system (Military, Treasury, Food, Public Support on 0–100 scales). See README.md for full game rules and world design.

## Development Environment

- Python 3.13, managed with `uv`
- Run all Python commands via `uv run` (e.g., `uv run python`, `uv run pytest`, `uv run jupyter`)
- Install dependencies: `uv sync`
- Run the game: `uv run python run_game.py [num_turns]`
- Environment variables required in `.env`: `OPENROUTER_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`

## Key Dependencies

- **pydantic-ai**: Agent framework — used for country agents, facilitator, and summary agents
- **openrouter**: LLM access (model: `openrouter:anthropic/claude-sonnet-4-6`, set in `islandsim/agents.py`)
- **langfuse**: Observability/tracing — agents instrumented via `Agent.instrument_all()` in `run_game.py`, game functions decorated with `@observe`
- **pydantic**: Data models for world state, actions, and turn resolution (all in `islandsim/models.py`)

## Project Structure

- `run_game.py` — CLI entrypoint, loads env/instrumentation, runs the async game loop
- `islandsim/models.py` — Pydantic models: `WorldState`, `NationState`, `Resources`, `TurnActions`, `Action`, `TurnResolution`, `GameSummary`, etc.
- `islandsim/agents.py` — Agent definitions (3 country agents + facilitator + summary agent), `NationContext`/`FacilitatorContext` dataclasses
- `islandsim/game.py` — Game loop: `run_game()` orchestrates turns, `collect_actions()` runs country agents concurrently, `resolve_turn()` calls facilitator, `generate_summary()` produces end-game assessment
- `islandsim/config.py` — `STARTING_STATE` (hardcoded initial world state), `ECONOMIC_RULES` and `ACTION_MENU` text blocks used in prompts
- `islandsim/prompts.py` — System prompts for each nation and the facilitator, plus per-turn prompt builders (`build_country_prompt`, `build_facilitator_prompt`, `build_summary_prompt`)
- `test_pydantic.ipynb` — Early demo notebook (pydantic-ai + langfuse integration)

## Architecture

The game loop (`run_game`) each turn: (1) runs all 3 country agents concurrently via `asyncio.gather`, each returning structured `TurnActions`, (2) passes all actions to the facilitator agent which returns a `TurnResolution` with updated `WorldState`, narrative, and private intel, (3) distributes private intel and tracks event injection timing. After all turns, a summary agent generates a `GameSummary`.

All agent outputs use pydantic-ai's structured output — agents return typed Pydantic models, not free text. Country agents see their own resources, public info about others, relationships, history, and any private intel they've accumulated. The facilitator sees everything including secret actions.
