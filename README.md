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

IslandSim is a working MVP. The full game loop runs end-to-end and produces coherent, interesting outcomes.

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

## Roadmap

Ordered roughly by impact-to-effort ratio. Each step builds on the ones before it.

### 1. Structured game logs

Save each turn's `TurnActions` and `TurnResolution` as JSON/JSONL alongside the narrative output. This is the foundation for everything else — analysis, replay, regression testing, and evaluation all require machine-readable data. [IMPLEMENTED 3/25/26]

### 2. Rule engine for standard actions

Add a programmatic layer that applies resource costs for standard actions (deploy patrol = -10 Military, -5 Treasury) before the facilitator sees them. The facilitator still handles ambiguous outcomes and narrative, but the baseline math is enforced. Validate that facilitator outputs respect resource bounds. [IMPLEMENTED 3/30/26]

### 3. Scenario configuration

Extract `STARTING_STATE`, `ECONOMIC_RULES`, and nation profiles into data files (YAML or TOML). Start with one variant scenario to prove the abstraction, then expand. [IMPLEMENTED 4/14/26]

### 4. Human plays one nation (TUI)

Add a playable interface where a human controls one nation while the other two remain AI-driven. Human input produces the same `TurnActions` model as AI agents, so the rule engine, facilitator, validation, and structured logs stay unchanged. [IMPLEMENTED 4/20/26] — shipped as a Textual TUI (`--play <nation>`) driven by a long-lived `GameApp` with Briefing / Waiting / Resolution / Summary screens. AI country agents run as background tasks during the briefing so the human isn't blocked and their failures can't cancel the briefing.

### 5. Stochastic resolution

Add a `resolve(attacker, defender, difficulty)` function to the rule engine and expose it to the facilitator as a tool. The facilitator still chooses *when* to roll and sets difficulty based on narrative context; the engine returns a binding random result. This injects genuine uncertainty into outcomes that are currently decided by facilitator judgment alone (where Haiku runs have shown bias — every covert Tauma operation was detected).

First cut:

- Add an `intel_skill` field to `NationState`, seeded per-nation from the scenario YAML (e.g. Veldara "sophisticated" → high, Tauma "crude" → low). One skill used for both offense and defense to keep the first iteration simple; split later if asymmetric capability becomes interesting.
- Roll is opposed: attacker `intel_skill` vs. defender `intel_skill`, modulated by difficulty and optionally by resource state (e.g. a nation with very low Military has less operational cover for espionage).
- Scope the tool to espionage / covert detection first, then expand to other judgment calls (typhoon severity, custom-action success degree).
- Log every tool call in `TurnRecord` so we can audit whether the facilitator is re-rolling or selectively skipping the tool to steer the narrative. System prompt should enforce "one roll per resolution event, result is binding."
[IMPLEMENTED 4/22/26] — `intel_skill` is seeded from scenario YAML, `skill_roll` is exposed as a facilitator tool, `--seed` makes skill-roll noise reproducible, and `TurnResolution.skill_rolls` records every tool call.

Once skills exist, add an `invest_intelligence` standard action that spends Treasury to raise `intel_skill` over time — turning capability into a strategic investment rather than a fixed trait.

### 5.5 Reproducibility / testing

- Add unit tests for scenario loading, economic adjustments, action costs, state-change application, seeded skill rolls, and log rendering.
- Add a mock or recorded LLM path that replays fixed agent responses for full-loop regression tests without live model calls.
- Keep run metadata in every new `GameLog` (`scenario_name`, model names, seed, mode, config snapshot) so cross-run comparisons are meaningful.

### 6. Empirical loop (batch runs + evaluation)

- Script that runs N games with a given configuration (scenario × models × prompt variant), collects structured outputs, and reports aggregate metrics: who controls Reef Maru, average resource deltas, conflict vs. negotiation frequency, distribution of final scores.
- Log schema additions needed first: model identifiers, scenario name, prompt version so runs are comparable.
- Evaluation layer on top: per-nation strategy classification, facilitator consistency scoring (e.g. are costs applied coherently across runs?), resource trajectory shape. Create score card
- Goal: be able to say "change X moved outcome Y by Z"  

### 7. Model benchmarking

Once #6 exists, use it to compare models on a defined axis. Primary interest: can a local or small model (qwen, gpt-oss, a smaller Claude) replace larger models for the country agents without meaningful quality loss? Need a concrete quality floor before running — e.g. "narrative coherence score within 10% of Sonnet baseline, turn latency under 15s."  

### 8. Wrap and restart

IslandSim is a toyy learning project; at some point it's more valuable to start fresh with everything learned than to keep extending the toy. The intriguing possibility is packaging the lessons as a skills/plugin set for coding agents — a reusable scaffold for building structured multi-agent simulations.

Use `LESSONS.md` to track insights along the way.

 
 

 
