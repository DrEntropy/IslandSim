# IslandSim

A multi-agent tabletop exercise simulator where AI agents represent three island-nations negotiating over a disputed resource discovery. A learning exercise and a test of agentic AI as a stand-in for human decision makers in strategic simulations.

![Kalani Archipelago](kalani-archipelago-map.svg)

## Setup

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager)
- An [OpenRouter](https://openrouter.ai/) API key
- A [Langfuse](https://langfuse.com/) account (for observability/tracing, optional)

### Install

```bash
git clone <repo-url> && cd IslandSim
uv sync
```

### Configure environment

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY="your-openrouter-key"
LANGFUSE_SECRET_KEY="sk-lf-..."  # leave these keys out to disable tracing.
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"
```

You can use other providers by changing the model strings in `config.yaml`. For example, to use Anthropic directly instead of OpenRouter, set `models.country` and/or `models.facilitator` to values like `anthropic:claude-sonnet-4-6` and provide the corresponding provider API key in `.env` (for example `ANTHROPIC_API_KEY` instead of `OPENROUTER_API_KEY`).

### Run

```bash
uv run python run_game.py                          # default scenario (reef_maru), 4 turns
uv run python run_game.py 8                         # custom turn count
uv run python run_game.py --scenario south_china_sea  # variant scenario
uv run python run_game.py 2 --scenario reef_maru    # quick 2-turn test
uv run python run_game.py --play naru              # play as Naru in the TUI (AI runs the other two)
uv run python run_game.py 6 --play veldara --scenario south_china_sea  # custom human game
```

### Reading game logs

Every run writes a structured `GameLog` JSON file to `logs/`. New runtime logs are ignored by default so smoke runs do not dirty the worktree; force-add a log only when it is meant to become a curated reference artifact. The `islandsim-log` console script renders one into a human-readable transcript (run metadata, actions, events, narrative, resource deltas per turn, plus the final summary):

```bash
uv run islandsim-log                              # newest log in logs/ → stdout
uv run islandsim-log logs/islandsim_<ts>.json     # specific log
uv run islandsim-log --out transcript.txt         # write to file
uv run islandsim-log --verbose                    # also include reasoning, action results, private intel
```

### Playing as a human (TUI)

Use `--play <nation>` to take control of one nation while the other two remain AI-driven. Valid values are `naru`, `veldara`, or `tauma`. The interface is a full-screen [Textual](https://textual.textualize.io/) TUI — make sure your terminal window is reasonably large (roughly 140×40 or more) or things will wrap.

One long-lived `GameApp` owns the whole session, rotating between four screens:

1. **Briefing** — your resources, other nations, pairwise relationships, world status (Reef Maru, Naru Strait, active effects), plus a History / Private Intel tab. The action panel on the right has four category buttons (Military / Economic / Diplomatic / Domestic), a filtered list of actions with cost + affordability indicators, and a queue of the 1–3 actions you're building. Focus starts on the action list so arrow keys + Enter work immediately.
2. **Action modal** — pops when you pick an action: pre-filled description you can edit (e.g. rewrite "Propaganda campaign" as "Propaganda campaign blaming Veldara for Reef Maru tensions"), visibility (Public/Secret), and a target nation when applicable. "Custom…" opens a free-text variant with no pre-fill.
3. **Waiting** — shown while the AI country agents finish (they run concurrently during your briefing) and the facilitator resolves the turn. Facilitator calls usually take 20–40 s.
4. **Resolution** — narrative of what happened, any world event injection, your resource delta table (before / after / change), and new private intel. Press Enter or click Continue to advance.

After the last turn, a final **Summary** screen shows the `GameSummary` narrative, Reef Maru outcome, and per-nation assessments. The structured `GameLog` is saved to `logs/` as with any AI-only run.

Notes:

- Affordability is indicated (✓/✗) but doesn't block; the rule engine is still the source of truth for costs and bounds.
- If you don't see keyboard focus where you expect, Tab cycles through widgets on the current screen.

### Configuration

**Scenarios** are defined in `scenarios/*.yaml`. Each file specifies nation profiles, starting resources, economic parameters, relationships, action costs, and narrative context.

**Operational config** (`config.yaml` at project root, optional) controls model selection, retries, default turns, and whether Langfuse tracing is enabled:

```yaml
models:
  country: "openrouter:anthropic/claude-haiku-4.5"
  facilitator: "openrouter:anthropic/claude-sonnet-4-6"
retries: 2
default_turns: 4
langfuse: true
```

Set `langfuse: false` to disable tracing explicitly. Tracing is also disabled automatically if `LANGFUSE_SECRET_KEY` is not present in `.env`.

To test with cheaper models or fewer turns, edit `config.yaml` — no code changes needed.

## Testing

The repo ships with a small `pytest` suite that pins the deterministic, non-LLM surface — `apply_changes`, `skill_roll`, and `GameLog` validation. It runs in well under a second, makes no network or LLM calls, and is the right thing to run before any change to `islandsim/rules.py` or `islandsim/models.py`.

```bash
uv sync --group dev          # one-time: install pytest into the dev group
uv run --group dev pytest    # run the full suite
uv run --group dev pytest -v # verbose, per-test output
```

Layout:

- `tests/test_apply_changes.py` — every `StateChange` variant (resource, relationship, strait, effect add/remove, reef-maru status), clamping at 0/100 and ±100, the warning paths for missing relationships and absent effects, and a mixed-list ordering check.
- `tests/test_skill_roll.py` — seeded reproducibility, the `[-30, 30]` roll bound, the `attacker - defender - difficulty + roll` margin formula, the `margin >= 0` success boundary, and that difficulty subtracts cleanly under a fixed seed.
- `tests/test_game_log.py` — `GameLog` JSON round-trip, optional `metadata` back-compat, the `TurnResolution._parse_json_string` validator (which coerces stringified-list outputs from misbehaving LLMs back into real lists), and pydantic constraint enforcement on `Resources` and `Relationship.sentiment`.

The LLM-driven loop (country agents, facilitator) is **not** under test — see [Future ideas](#future-ideas) for what that would take.

## How It Works

Three country agents (Naru, Veldara, Tauma) and one facilitator agent play a turn-based game over a configurable number of turns. Each turn:

1. All three country agents submit 1–3 actions concurrently (public or secret). Each action is classified as a standard type (via `StandardActionType` enum) or custom (`None`).
2. A rule engine applies deterministic per-turn economic adjustments (income, food, threshold penalties) and pre-deducts resource costs for standard actions.
3. The facilitator resolves all actions — pre-applied costs are communicated so they aren't double-counted. It returns narrative, per-action results, private intel, and a **declarative list of typed state changes** (see below). The facilitator handles narrative, ambiguous outcomes, custom action costs, and event injection.
4. The rule engine mechanically applies each state change with clamping and audit logging — the facilitator never mutates state directly.
5. Private intel is revealed only to intended recipients.

After all turns, a summary agent produces a narrative assessment and per-nation outcome review. All agent outputs are structured Pydantic models, not free text.

For full game rules, scenario details, and nation profiles, see [DESIGN.md](DESIGN.md).

### State changes: declarative deltas, not rewrites

Rather than having the facilitator LLM return a rewritten `WorldState`, it returns a `list[StateChange]` on `TurnResolution` — a discriminated union of typed mutations (`ResourceChange`, `RelationshipChange`, `StraitChange`, `ActiveEffectAdd`/`Remove`, `ReefMaruStatusChange`). Each change carries a signed `delta` (or new value) and a `reason` string used for the audit log. The Python engine (`apply_changes` in [islandsim/rules.py](islandsim/rules.py)) applies each change with clamping and records the realized effect; invalid references (e.g. removing a nonexistent effect) are logged as warnings instead of silently corrupting state.

Why this shape rather than a full state rewrite or per-mutation tool calls:

- **Atomicity with narrative.** Turn resolution is one coherent event. A single structured output keeps the narrative, action results, private intel, and the concrete mutations aligned — there's no drift between "what the story says happened" and "what changed."
- **LLM proposes, engine disposes.** Clamping (0–100 resources, ±100 sentiment), field lookup, and validation live in Python, not in prompt rules the model might violate. Facilitator output is safe to apply by construction.
- **Auditability.** Every mutation carries a `reason`, and the engine emits a human-readable effect line (`naru.military -5 (60 → 55)`). Together with the structured `GameLog`, runs are fully replayable and inspectable after the fact.
- **Type safety.** The `Annotated[Union[...], Field(discriminator="kind")]` pattern means pydantic-ai enforces the shape at parse time — each change is exhaustively one of the known kinds.
- **Composable with deterministic pre-processing.** Because the engine applies economic rules and standard action costs *before* the facilitator runs, the LLM's change list only needs to cover second-order effects and unmatched/custom actions. If the facilitator wants to override a pre-applied cost, it emits a compensating `ResourceChange` with a reason explaining why.

The alternative of exposing mutations as LLM tools (`adjust_resource(nation, field, delta)`, etc.) is a common pattern in modern agent frameworks, but it fits worse here: it multiplies round-trips, makes it harder to keep the narrative aligned with the mutations, and offers little benefit when resolution is atomic per turn.  

## Architecture

See [docs/agent_flow.md](docs/agent_flow.md) for a Mermaid diagram of the
agentic flow (country agents → rule engine → facilitator → summary).

```
run_game.py              CLI entrypoint, env loading, instrumentation, log saving
scenarios/
  reef_maru.yaml         Default scenario (Kalani Archipelago crisis)
  south_china_sea.yaml   Variant scenario (Jade Shoal standoff)
config.yaml              Operational config: models, retries, default turns (optional)
islandsim/
  models.py              Pydantic schemas: WorldState, TurnActions, Action, StandardActionType, TurnResolution, GameSummary, etc.
  scenario.py            Scenario config models, YAML loader, auto-generated prompt text
  settings.py            Operational config model and loader
  agents.py              Agent factory, context dataclasses
  game.py                Game loop: collect_actions → rule engine → resolve_turn → validate → summary
  rules.py               Rule engine: economic adjustments, standard action costs, output validation
  prompts.py             System prompt builders and per-turn prompt builders
logs/                    Structured JSON game logs (new runtime logs ignored by default; curated reference logs can be force-added)
```

Key design choices:

- **YAML scenario files** for all game-specific configuration — nations, economics, action costs, narrative context
- **Separate operational config** (`config.yaml`) for model selection and runtime settings — swap models for regression testing without touching scenarios
- **pydantic-ai** for agent framework with structured output
- **Rule engine** for deterministic resource math — standard action costs enforced programmatically via `StandardActionType` enum on `Action`, with facilitator output validation
- **Auto-generated prompt text** — economic rules and action menu text rendered from scenario data, preventing drift between what agents are told and what the engine enforces
- **Langfuse** for observability — all game functions decorated with `@observe`, agents auto-instrumented
- **asyncio.gather** for concurrent country agent execution

## Status

IslandSim is a working MVP. The full game loop runs end-to-end and produces coherent, interesting outcomes.  Last run was added as log `logs/islandsim_20260425T175821.json` (5 turns, Sonnet facilitator, default scenario).  

### What works

- Three country agents with distinct personalities and asymmetric starting positions
- Facilitator agent that resolves actions, manages world state, and injects events
- Private intelligence system, relationship tracking, resource management (0–100 scales)
- Structured outputs throughout — every agent call returns typed Pydantic models
- Structured game logs — each run saves a complete JSON log to `logs/` with run metadata, initial state, per-turn actions/resolutions, and final summary
- Langfuse tracing for full observability into agent reasoning

### Observations from initial runs

The first completed run (4 turns) produced a negotiated three-party governance accord over Reef Maru rather than a military outcome. Key observations:

- **Agents develop distinct strategies consistent with their roles.** Naru played broker, Tauma leveraged naval dominance, Veldara used economic and technical leverage. These emerged from the prompts and starting positions without explicit scripting.
- **The facilitator generates meaningful events.** A typhoon forced tactical retreats; a media leak exposed back-channel diplomacy; revised survey data raised the stakes. These created genuine turning points.
- **Narrative coherence is strong.** The game produced a plausible four-month diplomatic arc with cause-and-effect chains across turns.
- ~~**Resource adjudication is inconsistent.** The facilitator applies costs loosely — sometimes ignoring the action menu guidelines, sometimes inventing resource changes with no clear basis. This is the biggest quality gap.~~ Resolved — a rule engine now enforces standard action costs and per-turn economic adjustments deterministically.
- **Facilitator model capacity matters a lot.** Informal comparison between Haiku 4.5 and Sonnet 4.6 as the facilitator (country agents held at Haiku, same scenario, 4 turns, post-deltas schema): Sonnet injected events on 3/4 turns, actively pruned stale `active_effects`, and emitted ~57 well-reasoned `StateChange` entries with specific `reason` strings. Haiku injected **zero** events, let effects accumulate without pruning, and showed strong support-inflation bias (one nation capped at 100 by turn 2). Narrative quality gap is expected; the surprising finding is that Haiku treats the wider structured-output schema as a budget to be minimized, dropping non-required fields and under-using optional levers like event injection. Takeaway: use Sonnet-class or better for the facilitator; Haiku is fine for country agents.

### Known limitations

- ~~**No deterministic adjudication.** Resource changes are entirely LLM-judged. The facilitator can and does ignore cost guidelines.~~ Resolved — rule engine enforces standard action costs and validates facilitator output.
- ~~**No structured output persistence.** Turn data is printed to stdout only — no machine-readable logs for cross-run analysis.~~ Resolved — structured game logs now saved to `logs/`.
- ~~**Single hardcoded scenario.** One starting state, one set of nation profiles, one inciting event.~~ Resolved — scenarios now loaded from YAML files with a `--scenario` flag.
- **No test suite.** The codebase has no automated tests.
- ~~**No repeatability mechanism.** Each run produces different outcomes with no seeding or replay capability.~~ Partially resolved — `--seed` makes rule-engine skill rolls reproducible, but LLM outputs are still provider/model dependent. Full replay still needs mocked or recorded agent responses.
- ~~**No validation of facilitator outputs.** The system doesn't check that the facilitator's updated world state is internally consistent (e.g., resource changes that don't add up, or values drifting outside 0–100 despite Pydantic constraints on the model).~~ Resolved — rule engine validates and corrects facilitator output.

- **TUI.** The TUI is functional but still a proof of concept. It now shows costs and affordability, but needs stronger input validation, terminal-size polish, and better handling for failed AI/facilitator calls.

## History

The roadmap that took IslandSim from initial sketch to MVP wrap-up, highlights only

- **Structured game logs** — *3/25/26.* Save each turn's `TurnActions` and `TurnResolution` as JSON alongside the narrative output.  
- **Rule engine for standard actions** — *3/30/26.* Programmatic layer that applies resource costs for standard actions (e.g. naval patrol = −10 Military, −5 Treasury) before the facilitator sees them.  The facilitator still handles ambiguous outcomes and narrative.
- **Scenario configuration** — *4/14/26.* Extracted starting state, economic rules, and nation profiles into YAML scenario files. 
- **Human plays one nation (TUI)** — *4/20/26.* Textual TUI (`--play <nation>`) driven by a long-lived `GameApp` with Briefing / Waiting / Resolution / Summary screens. Human input produces the same `TurnActions` model as the AI agents, so the rule engine, facilitator, validation, and structured logs stayed unchanged. 
- **Stochastic resolution** — *4/22/26.* `intel_skill` field on `NationState` seeded per-nation from scenario YAML. `skill_roll` exposed as a facilitator tool (opposed check, attacker vs. defender skill, with difficulty). Every tool call is logged to `TurnResolution.skill_rolls` so we can audit whether the facilitator is re-rolling or selectively skipping the tool to steer the narrative. Scoped to espionage / covert detection initially; never expanded further.
- **Declarative state changes instead of WorldState rewrites** — *4/23/26.* Switched the facilitator's structured output from a rewritten `WorldState` to a `list[StateChange]`  See: [State changes: declarative deltas, not rewrites](#state-changes-declarative-deltas-not-rewrites) for the full design rationale.
- **Initial test suite for the non-LLM surface** — *4/25/26.*   See [Testing](#testing).

## Future ideas

- **Test the LLM surface.** The current `tests/` suite covers only the non-llm surface — `apply_changes`, `skill_roll`, and `GameLog` validation. A future iteration could exercise the full agent loop by replacing the `pydantic-ai` country and facilitator agents with a Mock that either replays old `GameLog` traces or returns scripted `TurnActions` / `TurnResolution` objects.  
- **Strategic intelligence investment.** Add an `invest_intelligence` standard action that spends Treasury to raise `intel_skill` over time, turning espionage capability into a strategic investment rather than a fixed scenario-seeded trait. Currently `intel_skill` is set once at game start and never moves.
- **Empirical loop (batch runs + evaluation).** Script that runs N games over a configuration grid (scenario × models × prompt variant), collects the structured outputs, and reports aggregate metrics: who controls Reef Maru, average resource deltas, conflict-vs.-negotiation frequency, distribution of final scores. Layer on per-nation strategy classification and facilitator consistency scoring (are costs applied coherently across runs?). Goal: be able to say "change X moved outcome Y by Z"   
- **Model benchmarking.** Once the empirical loop exists, use it to compare models on a defined axis. Primary interest: can a local or small model (qwen, gpt-oss, a smaller Claude) replace larger models for the country agents without meaningful quality loss? Needs a concrete quality floor before running — e.g. "narrative coherence score within 10% of Sonnet baseline, turn latency under 15 s."
- **Reusable multi-agent simulation scaffold.** The most intriguing direction is packaging the lessons as a skills/plugin set for coding agents — a reusable scaffold for building structured multi-agent simulations (typed agent I/O, declarative state changes, hybrid rule-engine + LLM resolution, structured logs).  

 
 

 
