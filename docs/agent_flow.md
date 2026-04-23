# Agentic Flow

How the IslandSim agents interact across a game run. Code references are in
`islandsim/game.py`, `islandsim/agents.py`, and `islandsim/rules.py`.

## High-level flow

```mermaid
flowchart TD
    subgraph Setup["Setup (run_game)"]
        A1["load_scenario(scenarios/*.yaml)"] --> A3["create_agents()"]
        A2["load_settings(config.yaml)"] --> A3
        A3 --> A4["3 country agents + facilitator + summary agent<br/>(pydantic-ai Agent instances)"]
        A4 --> A5["scenario.to_starting_state() → WorldState"]
    end

    Setup --> Loop

    subgraph Loop["Per-turn loop (turns 1..N)"]
        direction TB
        P1["Phase 1: collect_actions()<br/>asyncio.gather over 3 country agents"]
        P15["Phase 1.5: Rule engine<br/>apply_economic_adjustments()<br/>apply_action_costs()"]
        P2["Phase 2: resolve_turn()<br/>Facilitator agent"]
        P25["Phase 2.5: validate_resolution()<br/>(re-asserts pre-applied costs)"]
        P3["Distribute private_intel, append history,<br/>track turns_since_event, append TurnRecord"]

        P1 --> P15 --> P2 --> P25 --> P3
    end

    Loop --> S1["generate_summary()<br/>Summary agent → GameSummary"]
    S1 --> S2["Persist GameLog → logs/islandsim_*.json"]
```

## Phase 1 — country agents (concurrent)

Each country agent sees only its own private intel plus public world state,
and returns a structured `TurnActions` (typed pydantic-ai output).

```mermaid
flowchart LR
    WS["WorldState<br/>(public view)"] --> N
    WS --> V
    WS --> T
    INTEL_N["private_intel[Naru]"] --> N
    INTEL_V["private_intel[Veldara]"] --> V
    INTEL_T["private_intel[Tauma]"] --> T
    HIST["shared history (narratives)"] --> N & V & T

    N["Naru agent"] --> TAN["TurnActions (Naru)"]
    V["Veldara agent"] --> TAV["TurnActions (Veldara)"]
    T["Tauma agent"] --> TAT["TurnActions (Tauma)"]

    TAN & TAV & TAT --> AGG["dict[NationName, TurnActions]"]
```

Country agents classify each action with `StandardActionType` (or leave it
`None` for creative/custom actions). Costs for standard actions are
deterministic and applied by the rule engine, not the LLM.

## Phase 1.5 — rule engine

```mermaid
flowchart LR
    IN["WorldState + all_actions"] --> EA["apply_economic_adjustments()<br/>income, food, support penalties"]
    EA --> AC["apply_action_costs()<br/>deducts standard action costs"]
    AC --> OUT1["adjusted WorldState"]
    AC --> OUT2["applied_costs (list)"]
    AC --> OUT3["unmatched actions (custom)"]
```

## Phase 2 — facilitator resolution

The facilitator receives the post-rule-engine state, is told which costs are
already applied, and only resolves unmatched/custom actions and narrative.
It can invoke the `skill_roll` tool (opposed roll against `intel_skill`)
for covert-action detection. Rolls are appended to `FacilitatorDeps.roll_log`
and surfaced on the returned resolution.

```mermaid
flowchart TD
    FIN["adjusted WorldState<br/>+ all_actions<br/>+ applied_costs<br/>+ unmatched_actions<br/>+ history + turns_since_event"] --> FA

    FA["Facilitator agent"]

    FA -.tool.-> SR["skill_roll()<br/>(opposed roll vs intel_skill)"]
    SR -.margin / success.-> FA

    FA --> RES["TurnResolution<br/>• updated_state<br/>• narrative<br/>• event_injected?<br/>• private_intel per nation<br/>• skill_rolls"]

    RES --> VAL["validate_resolution()<br/>re-applies pre-deducted costs<br/>if facilitator drifted"]
    VAL --> NEXT["feed back into next turn"]
```

## End of game

```mermaid
flowchart LR
    FSTATE["final WorldState + history"] --> SUM["Summary agent"]
    SUM --> GS["GameSummary<br/>(narrative, reef_maru_outcome,<br/>nation_assessments)"]
    GS --> LOG["GameLog (initial_state,<br/>per-turn TurnRecords, summary)"]
    LOG --> FILE["logs/islandsim_&lt;ts&gt;.json"]
```

 