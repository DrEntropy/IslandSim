# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IslandSim is a multi-agent tabletop exercise simulator where AI agents represent three island-nations (Naru, Veldara, Tauma) negotiating over a disputed resource discovery. A Facilitator agent acts as GM, resolving actions and injecting events. The game runs turn-based over 6–10 turns with a resource system (Military, Treasury, Food, Public Support). See README.md for full game rules and world design.

## Development Environment

- Python 3.13, managed with `uv`
- Run all Python commands via `uv run` (e.g., `uv run python`, `uv run pytest`, `uv run jupyter`)
- Install dependencies: `uv sync`
- Environment variables required in `.env`: `OPENROUTER_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL`

## Key Dependencies

- **pydantic-ai**: Agent framework — used for country agents and facilitator
- **openrouter**: LLM access (models referenced as `openrouter:anthropic/claude-sonnet-4-6`)
- **langfuse**: Observability/tracing — agents are instrumented via `Agent.instrument_all()` and `@observe` decorators

## Current State

Early prototype. The only code so far is `test_pydantic.ipynb`, a demo of pydantic-ai + langfuse integration. The actual simulation (country agents, facilitator, game loop, world state) has not been implemented yet. The MVP plan in README.md outlines next steps: hardcode world state as JSON config, implement facilitator and country agents as LLM calls, run a few turns manually.
