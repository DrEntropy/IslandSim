# Lessons Learned

Running notes on what's worked, what hasn't, and what to carry forward to a future iteration.  See `haiku_run_analysis.md` for the full transcript-level analysis that seeded several of these.

## Scaffolding

- **Typed Pydantic I/O everywhere pays off.** Agent outputs as structured models (not free text) makes the rule engine, validation, logging, and TUI all trivially composable. The one time an agent produces unstructured prose is inside a `reasoning` field where it doesn't matter.
- **Rule engine + facilitator hybrid works better than either alone.** Pre-applying standard action costs deterministically, then letting the facilitator narrate + handle the ambiguous residue, gives you mechanical consistency without killing narrative flexibility. But *any* cost the facilitator gets to invent is a place where bias creeps in (see Haiku Turn 2: -25/-20 for a covert base, out of thin air).
- **Auto-generated prompt text from scenario data prevents drift.** Economic rules and action menus rendered from the YAML means agents are told exactly what the engine enforces. Do this from day one in the next iteration — retrofitting it is annoying.

## Agent behavior

- **Character stability from trait descriptions alone is surprisingly robust.** Four turns in, Naru is still "pragmatic/transactional," Veldara still "legalistic," Tauma still "aggressive-then-desperate" — with no explicit "stay in character" reinforcement between turns. The scenario YAML traits do most of the work.
- **Agents over-reason when the prompt invites essay writing.** The Haiku run had 500–1000 words of strategic analysis per country per turn, much of it filler ("RATIONALE," "PROJECTION," "RISKS MANAGED"). A tighter reasoning schema (top-3 constraints, top-3 opportunities, chosen actions) would likely produce sharper play at a fraction of the tokens.
- **Emergent coordination is real but suspicious.** Two nations independently sending 10 Treasury of aid to the same target on the same turn is striking — but how much of that is genuine convergent strategy vs. the shared world-state description implicitly steering them? Worth instrumenting in future runs (e.g. blind one agent to a piece of context and see if convergence survives).
- **Small model (Haiku) is sufficient for country agents.** The strategic quality is coherent and in-character. Reserve larger models for the facilitator where narrative judgment and consistency across all three perspectives matters more.

## Balance and mechanics

- **Unchecked facilitator discretion creates systematic bias.** In the Haiku run, every single covert Tauma operation was detected.  This is just the facilitator judgment. This is the core motivator for stochastic resolution (roadmap #5).
- **Support inflation is a rule-engine gap.** All three nations ended at 100 Support despite wildly different strategic positions. The facilitator grants +5 for almost any public action framed sympathetically, and the rule engine doesn't cap aggregate Support gains. Either cap Support deltas per turn, or tie Support more directly to resource-reality thresholds (food crisis → support drain, military collapse → support drain).
- **Strategic texture plateaus at ~4 turns with the current rule set.** There's nothing to *do* with Reef Maru once claimed. This suggests setting up the system to do as many turns necessary to get to the end state.  It also suggests in future system to add more 'what happens next' to keep the game going? 
- **Secret actions are the highest-leverage mechanic.** More strategic texture came out of covert ops + detection than any other system. This also motivates the choice of espionage as teh first new mechanic to add in the next iteration for stocahstic resolution.

## Tooling and observability

- **Langfuse tracing + structured JSON logs cover ~90% of the debugging need.** Didn't need a bespoke log viewer. Worth noting before building one.
- **Per-run analysis documents (like `haiku_run_analysis.md`) are high-value artifacts.** A one-shot written pass over a transcript finds patterns that aren't visible in aggregate metrics or while watching a run live. One per meaningful milestone is the right cadence.

## Architecture decisions to carry forward

- Scenario/operational config split (`scenarios/*.yaml` vs. `config.yaml`) — clean separation, easy to swap models without touching game data. Keep.
- `StandardActionType` enum + custom-action escape hatch — gives deterministic costs for the common case and lets agents invent creative moves for edge cases. Keep.


 