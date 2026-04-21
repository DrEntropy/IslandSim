# Haiku Run Analysis — Reef Maru, 4 Turns

Log: `logs/islandsim_20260420T202246.json` — Claude Haiku 4.5 playing all three country agents and the facilitator over 4 turns of the Reef Maru scenario.

## What Happened

**Turn 1 — The Scramble.** All three nations did roughly the same thing: a sovereignty declaration + naval patrol to Reef Maru, plus one ancillary move. Naru anchored on "neutral strait guarantor," Veldara on legal appeals, Tauma on naval dominance + early espionage. Zero contact, three fleets within sight of each other.

**Turn 2 — Tauma's Gambit.** Tauma ran a covert base-building operation at Reef Maru. The facilitator improvised a heavy price (-25 Military, -20 Treasury — zeroing Tauma's treasury) and ruled Veldara's "sophisticated intel" spotted it. The first typhoon grazed the region and knocked out a Tauma food convoy. Meanwhile Naru-Veldara warmed into a formal trade agreement, and Tauma pivoted publicly with a defense-pact proposal to Naru.

**Turn 3 — Aid Offensive + Espionage Blowup.** Naru *and* Veldara independently sent Tauma 10 Treasury in humanitarian aid (same turn, unprompted — striking convergence). Veldara simultaneously escalated by establishing a permanent military base on Reef Maru. Tauma ran a second covert op — espionage against Veldara — which was again detected and blocked, driving Veldara-Tauma sentiment to -35. Second, larger typhoon forecast.

**Turn 4 — Humanitarian Evacuation.** All three nations independently converged on evacuating Reef Maru ahead of the typhoon. Tauma sent a "secret" private cable to Naru proposing bilateral alignment; Naru's signals intel intercepted it. Naru shared the intercept with Veldara, cementing a Naru-Veldara bloc. Final state: Reef Maru abandoned but contested, Naru-Veldara at +25, Tauma isolated at 0 and -45.

## Final Resource Snapshot

|        | Military | Treasury | Food | Support |
|--------|----------|----------|------|---------|
| Naru    | 0        | 25       | 63   | 100     |
| Veldara | 0        | 15       | 96   | 100     |
| Tauma   | 15       | 10       | 32   | 100     |

All three ended with 100 Support. Military collapsed across the board.

## What the Run Teaches About This Kind of Workflow

**The narrative coherence is genuinely impressive.** Four turns produced a legible three-act arc: scramble → escalation → humanitarian pivot → diplomatic endgame. Each country stayed in character across turns — Naru pragmatic/transactional, Veldara legalistic/stewardly, Tauma aggressive-then-desperate — without any explicit "remember your character" prompting between turns. The scenario file's trait descriptions carry a lot of weight here.

**Structured output + a rule engine is doing the heavy lifting.** Standard-action cost pre-application ([rules.py](islandsim/rules.py)) means the facilitator isn't hallucinating costs for most moves. But the places where it gets to improvise — secret/custom actions like Tauma's covert base and espionage — show the risk: the facilitator invented a -25/-20 cost for the covert base on Turn 2 with no rule-engine backing. That number shaped the entire rest of the game (Tauma's treasury collapse drove the aid offensive, which drove the alliance formation). A different facilitator roll could have produced a very different story.

**Emergent coordination is real but suspicious.** Naru and Veldara both sending 10 Treasury of aid to Tauma on Turn 3 with no prior negotiation is striking. Did the agents independently reach the same "stabilize the weak player" instinct, or is the facilitator's shared world-state summary implicitly steering them toward convergent moves? Probably both. Either way, it's the kind of dynamic you wouldn't design by hand.

**Secret actions are the most interesting system.** Every Tauma covert op got detected. The facilitator's detection rulings are consistent (Veldara's "sophisticated intel" beats Tauma's "crude" apparatus, per the traits) but not mechanical — there's no dice roll, just narrative judgment. This is where the workflow most resembles a human GM, and also where it's least reproducible.

**Support inflation is a balance problem.** Every nation ended at 100 Support despite wildly different situations — Tauma is financially broken, militarily exposed, and strategically isolated, but its population is "maximally supportive." The facilitator grants +5 Support for almost every public action framed sympathetically. Either the rule engine should cap Support gains more aggressively, or the facilitator needs a "Support reflects strategic reality" instruction.

**The agents over-reason.** Each country's reasoning field is 500–1000 words of strategic analysis per turn. Most of it is reasonable but much is filler ("PROJECTION," "RATIONALE," "RISKS MANAGED" with the same three bullets). Haiku is cheap enough that this doesn't matter for cost, but it suggests the country-agent prompt is inviting performative analysis rather than decision-focused planning. A tighter output schema (top-3 constraints, top-3 opportunities, chosen actions) might produce sharper play.

**Four turns is the sweet spot for this structure.** Turn 1 is setup, Turn 2 introduces a shock, Turn 3 forces a strategic pivot, Turn 4 resolves or freezes. Longer runs would likely loop (another typhoon, another aid package) without deepening the strategic texture, because the rule engine doesn't yet model the long-tail consequences that would force genuinely new decisions (e.g., actually developing the rare earth deposit, regime collapse thresholds, third-party intervention).

## Bottom Line

The run is a successful proof that a cheap model + good scaffolding (typed Pydantic I/O, a deterministic rule engine, scenario-driven traits, a facilitator with consistent narrative voice) can produce a coherent multi-agent tabletop exercise. The weaknesses are all in the seams: facilitator discretion on custom-action costs, support inflation, and agent prompts that reward essay-writing over decision-making. None of those are model-capability problems — they're scaffolding problems, which means they're fixable.
