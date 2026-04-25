# Lessons Learned

Drawn primarily from the final reference run (`logs/islandsim_20260425T175821.json`): 5 turns, Haiku country agents, Sonnet facilitator, default `reef_maru` scenario.  

## Scaffolding

- **Typed Pydantic I/O end-to-end is the right framework** Agent outputs as structured models (not free text) make the rule engine, validation, logging, and TUI all trivially composable. The one place an agent produces unstructured prose is inside a `reasoning` field where it doesn't matter.
- **Rule engine + facilitator hybrid works better than either alone.** Pre-applying standard action costs deterministically, then letting the facilitator narrate and handle the ambiguous residue, gives mechanical consistency without killing narrative flexibility. Veldara's Turn 2 base attempt — pre-applied costs, then partially reversed by the facilitator when the action failed because military hit zero — is a good example.
- **Declarative `StateChange` output from the facilitator is the right factoring.** The facilitator emits a typed list of mutations with a `reason` per change; the engine clamps and applies. ~10–15 changes per turn across the run with no schema warnings, and audit logging falls out for free. Far better than asking the facilitator to rewrite the world state.
- **Skill-roll tool exposed via pydantic-ai is the right factoring for stochastic resolution.** The facilitator can request an opposed roll mid-resolution; the engine provides the seeded RNG and logs the outcome. 16 rolls fired across 5 turns with mixed outcomes — successes and failures distributed across all three nations rather than systematically favoring whoever the facilitator might have implicitly preferred.
- **Auto-generated prompt text from scenario data prevents drift.** Economic rules and action menus rendered from the YAML mean agents are told exactly what the engine enforces. Do this from day one in any rebuild — retrofitting it is annoying.

## Agent behavior

- **Character stability from trait descriptions alone is robust.** Five turns in, Naru is still the pragmatic-architect, Veldara still the legalistic bridge-builder, Tauma still aggressive-then-defensive. There is no "stay in character" reinforcement between turns; the scenario YAML traits do the work.
- **Sonnet facilitator produces meaningfully more nuanced narrative than smaller models.** Willing to leave the outcome explicitly UNRESOLVED ("framework convergence in progress") rather than force a winner. The Turn 5 framing of Veldara's covert-aid confession as a strategic pivot is the kind of judgment a smaller facilitator did not reach in earlier runs. Cost is longer narratives and more tokens — worth it for the facilitator role specifically.
- **Small model (Haiku) might be sufficient for country agents.** Strategic reasoning is coherent and in-character. Naru's Turn 3 reasoning explicitly identifies the post-failed-Tauma-espionage window as the moment to strike — multi-turn opponent modeling at small-model scale.  Still need to test larger (and smaller) models on this role before concluding, but early signs are promising.
- **Agents over-reason when the prompt invites essay writing.** Country agents produce 500–1000 words of strategic analysis per turn (visible in `April25runVerbose.txt`), much of it filler ("RATIONALE", "PROJECTION", "RISKS MANAGED"). A tighter reasoning schema (top-3 constraints, top-3 opportunities, chosen actions) would likely produce sharper play at a fraction of the tokens.
- **Emergent coordination is real but suspicious.** Veldara's Turn 5 voluntary disclosure of its covert Tauma aid — perfectly timed to neutralize Tauma's coalition-evidence dossier in the same session — looks like genius play. But all three agents read the same world-state description; how much of this is convergent strategy vs. shared context implicitly steering them is unclear. Worth instrumenting in any future iteration (e.g. blind one agent to a piece of context and see if convergence survives).
- **Intelligence asymmetry from skill rolls compounds across the game.** Naru's successful Turn 3 espionage on Tauma seeded a durable info advantage that shaped Turns 4 and 5 (detected the resupply convoy, detected the investor approach). Tauma's Turn 2 failed espionage left it information-blind for the remaining 4 turns. The mechanic works as designed but variance is high — one early roll can dominate the run's strategic shape.

## Balance and mechanics

- **Stochastic resolution via skill rolls removes the systematic-facilitator-bias failure mode.** Earlier runs without skill rolls saw every covert operation by a particular nation get detected — pure facilitator judgment leaked into a pattern. With opposed rolls, successes and failures distribute realistically across nations. This is the single most important mechanical addition for narrative legitimacy.
- **Support inflation is the rule-engine's biggest gap.** All three nations end at 95–100 Support despite Tauma being militarily and economically gutted (M=5, T=12, F=33). The facilitator grants +5–20 for almost any sympathetic public action, and the rule engine doesn't cap aggregate Support gains. Either cap Support deltas per turn at the engine layer, or tie Support to resource-reality thresholds (food crisis → support drain, military collapse → support drain).
- **Facilitator-injected world events do the work the rule engine doesn't.** Typhoon Hana (Turn 2), RMAC mediation offer (Turn 3), investor consortium (Turn 4) — three injected events in five turns kept the strategic shape evolving. Without them, strategic texture would plateau around Turn 3–4: there is nothing in the rule set to *do* with Reef Maru once it is claimed and a base is built. A future iteration should add mechanical "what happens after a base is built" rather than leaning entirely on facilitator events.
- **Secret actions are the highest-leverage mechanic.** Of 9 actions per turn, the covert ones (espionage, secret aid, secret propaganda, secret investor proposal) drove every consequential plot beat. Espionage was the right first new mechanic to back with stochastic resolution; the same treatment should extend to other covert action types.
- **Pre-applied costs + facilitator residue handles failure cases cleanly.** Veldara's Turn 2 base failure (military at zero, can't force landing) is resolved by the facilitator emitting partial-reversal `StateChange`s rather than rewriting the world. Without the declarative-changes design, the facilitator would have had to re-narrate everyone's resources from scratch.
- **5 turns is about right for narrative texture under the current rule set.** The arc has a credible opening (claim race), middle (coercion + covert ops + crisis event), and end (mediation + framework convergence). Shorter would feel rushed; longer would either need more mechanical depth or repeated facilitator events.


## Architecture decisions to carry forward

- **Scenario/operational config split** (`scenarios/*.yaml` vs. `config.yaml`) — clean separation, easy to swap models without touching game data.
- **`StandardActionType` enum + custom-action escape hatch** — deterministic costs for the common case, agents can still invent creative moves for edge cases.
- **Declarative `StateChange` output from the facilitator** — is a good clean way to seperate "what changed" and "how it's narrated". This is better then providing 'state change' tools to the facilitator as it is easier to control the consistency and flow. (Note, I recognize that this is in fact implemented as a tool call in pydantic-ai, but it is a final non-returning tool.) 
- **Skill-roll tool exposed to the facilitator via pydantic-ai** — seems to be agood starting point for any stochastic resolution layer to grow into.
- **Pre-applied standard costs in the rule engine before the facilitator sees the turn** — keeps the facilitator focused on ambiguous residue, not bookkeeping.

 
