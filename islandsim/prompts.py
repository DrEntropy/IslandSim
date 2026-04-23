from __future__ import annotations

from typing import TYPE_CHECKING

from islandsim.models import NationName

if TYPE_CHECKING:
    from islandsim.agents import FacilitatorContext, NationContext
    from islandsim.models import WorldState
    from islandsim.scenario import ScenarioConfig


# ---------------------------------------------------------------------------
# Country agent system prompts
# ---------------------------------------------------------------------------

_COUNTRY_BASE = """\
You are the strategic decision-maker for the island-nation of {name}. You are \
playing a multi-turn tabletop exercise against two other AI-controlled nations. \
A Facilitator (game master) will resolve your actions each turn.

YOUR NATION:
{traits}

STRATEGIC CONTEXT:
{strategic_context}

RULES:
{economic_rules}

AVAILABLE ACTIONS:
{action_menu}

INSTRUCTIONS:
- Submit 1 to 3 actions per turn.
- Each action must be marked PUBLIC (announced to all) or SECRET (only the \
Facilitator sees it — but other nations may detect it through espionage).
- Think strategically about your nation's strengths, weaknesses, and \
dependencies on other nations.
- Consider both short-term tactical moves and longer-term positioning.
- Your reasoning field is private — use it to explain your strategic thinking.
"""


def build_country_system_prompt(nation: NationName, scenario: ScenarioConfig) -> str:
    """Build the system prompt for a country agent from scenario data."""
    nation_cfg = scenario.nations[nation.value]
    return _COUNTRY_BASE.format(
        name=nation.value.capitalize(),
        traits=nation_cfg.personality,
        strategic_context=scenario.strategic_context,
        economic_rules=scenario.render_economic_rules(),
        action_menu=scenario.render_action_menu(),
    )


_FACILITATOR_BASE = """\
You are the Facilitator (game master) for a multi-turn tabletop exercise \
involving three island-nations: {nation_names}. {scenario_description}

YOUR ROLE:
- Resolve all submitted actions simultaneously and impartially.
- Apply resource costs and gains according to the rules framework.
- Use judgment for ambiguous outcomes (e.g., does a secret negotiation get \
leaked? Consider espionage investments, how careful they were, etc.).
- Use probability-weighted judgment for uncertain outcomes — not pure dice, \
but not deterministic either.
- Model second-order effects (a blockade disrupts trade, which hits Treasury \
and Food for nations using that route).
- Maintain game balance and narrative interest.

ECONOMIC MODEL:
{economic_rules}

ACTION REFERENCE:
{action_menu}

RELATIONSHIP TRACKING:
Track sentiment between each pair of nations. Hostile actions decrease \
sentiment; cooperation increases it. Major betrayals cause large drops.

EVENT INJECTION:
{event_injection_guidance}, inject a world event to prevent stalemate and test \
adaptability. Examples: typhoon hits shipping lanes, pirate activity, a \
journalist leaks a secret deal, a foreign power expresses interest in \
the region, fishing stocks collapse, refugee crisis.

PRE-APPLIED COSTS:
A rule engine has already applied per-turn economic adjustments (income, food \
production/consumption, threshold penalties) and standard action costs to the \
world state you receive each turn. The resource values ALREADY reflect these \
changes. Do NOT restate them.

OUTPUT MODEL — STATE CHANGES:
You do NOT return a new world state. Instead, emit a list of typed \
``StateChange`` entries in the ``changes`` field; the game engine applies \
them to produce the next state. Every change carries a ``reason`` string \
used for the audit log — be specific and terse.

Change kinds:
- ``resource`` — adjust one of {{military, treasury, food, support}} for a \
nation by a signed ``delta``. Use this for any resource effects the rule \
engine did not pre-apply (unmatched actions, second-order effects, \
threshold adjustments, event consequences). Values are clamped to 0..100.
- ``relationship`` — shift sentiment between two nations by a signed \
``delta`` (clamped -100..100). Hostile actions decrease; cooperation \
increases; major betrayals cause large drops.
- ``strait`` — open or close the Naru Strait.
- ``effect_add`` / ``effect_remove`` — manage ``active_effects`` (ongoing \
conditions like "typhoon", "blockade in place").
- ``reef_maru_status`` — replace the narrative sovereignty string.

OVERRIDING A PRE-APPLIED ACTION:
If a pre-applied standard action is invalid or implausible in context \
(e.g. blockaded, can't deploy in a typhoon, resources too depleted, \
action pre-empted by a faster-acting nation), emit ``resource`` changes \
that NET OUT the original cost — fully or partially. The pre-applied \
cost deltas are listed in the turn prompt for reference; invert them \
(or a fraction) and cite the action by description in ``reason`` so the \
audit log shows the connection. Example: if Naru's NAVAL_PATROL \
pre-applied ``military -15, treasury -5`` but the strait is blockaded, \
emit ``resource`` changes ``naru.military +15`` and ``naru.treasury +5`` \
each with reason ``"NAVAL_PATROL cancelled: strait blockaded"``. Partial \
reversals are fine (e.g. +8 military if only half the deployment \
happened before events intervened).

Do NOT try to emit changes that mutate turn number, max_turns, nation \
identities, or intel_skill — those are engine-owned.

Your responsibilities:
- Emit ``resource`` changes for UNMATCHED actions (creative/novel actions \
not in the standard menu) and their second-order effects.
- Determine outcomes for ambiguous actions (espionage detection, \
negotiation results, blockade consequences beyond direct cost).
- Emit ``resource`` changes that net out a pre-applied cost when the \
action is invalid (see override pattern above).
- Emit ``relationship`` changes as warranted by the turn's events.
- Write ``narrative``, ``action_results``, and optionally ``event_injected``.

SKILL ROLLS (binding randomness):
A ``skill_roll`` tool is available. Use it to resolve covert-action \
detection: any time a secret/espionage action might or might not be \
detected by its target (or by a third party), call ``skill_roll`` \
with ``attacker`` = the nation taking the covert action, ``defender`` \
= the nation whose counter-intelligence would catch it, and \
``difficulty`` reflecting narrative context: 0 routine, +20 hard, +40 \
extreme (e.g. deep-cover infiltration of a well-guarded ministry).

Rules for skill rolls:
- **One roll per resolution event.** Do not re-roll the same detection \
question because you dislike the result.
- **The tool result is binding.** If it returns success, the covert \
action succeeds (detection fails / op is not exposed). If it returns \
failure, it is caught. Reflect that in narrative, ``detected_by``, \
and any consequences.
- **Provide a short, specific ``context`` string** naming the event \
(e.g. "Tauma attempts to infiltrate Veldara mining ministry"), so the \
audit log is legible.
- For the first cut, only use the tool for covert/espionage detection. \
Other judgment calls (typhoon severity, custom-action success degree) \
remain your narrative judgment.

RESOLUTION GUIDELINES:
- Do NOT re-emit changes for costs listed as pre-applied in the turn prompt.
- For unmatched actions: emit ``resource`` changes for their costs.
- For secret actions: call ``skill_roll`` to determine whether they are \
detected rather than deciding by narrative feel alone.
- Resource deltas are clamped to keep values in 0-100; you don't need to \
clamp yourself.
- If Support drops below {instability_threshold}, note government instability.
- Be specific about resource changes — state exact numbers.
- The narrative should be engaging and read like a news briefing.
- Start from the resource values shown (which include pre-applied costs).
"""


def build_facilitator_system_prompt(scenario: ScenarioConfig) -> str:
    """Build the facilitator system prompt from scenario data."""
    nation_names = ", ".join(
        n.capitalize() for n in scenario.nations
    )
    return _FACILITATOR_BASE.format(
        nation_names=nation_names,
        scenario_description=scenario.strategic_context,
        economic_rules=scenario.render_economic_rules(),
        action_menu=scenario.render_action_menu(),
        event_injection_guidance=scenario.game.event_injection_guidance.capitalize(),
        instability_threshold=scenario.game.instability_threshold,
    )


# ---------------------------------------------------------------------------
# User-prompt builders (per-turn context)
# ---------------------------------------------------------------------------


def build_country_prompt(ctx: NationContext) -> str:
    """Build the per-turn user prompt for a country agent."""
    state = ctx.world_state
    nation = state.nations[ctx.nation]

    # Build visible state summary
    lines = [
        f"=== TURN {state.turn} of {state.max_turns} ===\n",
        f"YOUR RESOURCES ({ctx.nation.value.upper()}):",
        f"  Military: {nation.resources.military}",
        f"  Treasury: {nation.resources.treasury}",
        f"  Food: {nation.resources.food}",
        f"  Support: {nation.resources.support}",
        f"  Intel Skill: {nation.intel_skill} "
        f"(your espionage/counter-intel capability, 0-100; "
        f"other nations' values are unknown to you)",
        "",
        "OTHER NATIONS:",
    ]

    for name, ns in state.nations.items():
        if name != ctx.nation:
            lines.append(
                f"  {name.value.upper()}: Military={ns.resources.military}, "
                f"Treasury={ns.resources.treasury}, Food={ns.resources.food}, "
                f"Support={ns.resources.support}"
            )

    lines.append(f"\nRELATIONSHIPS:")
    for rel in state.relationships:
        lines.append(
            f"  {rel.nation_a.value.upper()} — {rel.nation_b.value.upper()}: "
            f"sentiment {rel.sentiment:+d}"
        )

    lines.append(f"\nREEF MARU: {state.reef_maru_status}")
    lines.append(f"STRAIT: {'Open' if state.strait_open else 'BLOCKADED'}")

    if state.active_effects:
        lines.append(f"\nACTIVE EFFECTS:")
        for effect in state.active_effects:
            lines.append(f"  - {effect}")

    if ctx.history:
        lines.append(f"\nPREVIOUS TURNS:")
        for entry in ctx.history:
            lines.append(f"  {entry}")

    if ctx.own_private_intel:
        lines.append(f"\nPRIVATE INTELLIGENCE (only you know this):")
        for intel in ctx.own_private_intel:
            lines.append(f"  - {intel}")

    lines.append(
        f"\nSubmit your actions for turn {state.turn}. "
        f"Remember: you are {ctx.nation.value.upper()}."
    )

    return "\n".join(lines)


def build_facilitator_prompt(ctx: FacilitatorContext) -> str:
    """Build the per-turn user prompt for the facilitator."""
    state = ctx.world_state

    lines = [
        f"=== RESOLVE TURN {state.turn} of {state.max_turns} ===\n",
        "CURRENT WORLD STATE:",
    ]

    for name, ns in state.nations.items():
        lines.append(
            f"  {name.value.upper()}: Military={ns.resources.military}, "
            f"Treasury={ns.resources.treasury}, Food={ns.resources.food}, "
            f"Support={ns.resources.support}"
        )

    lines.append(f"\nRELATIONSHIPS:")
    for rel in state.relationships:
        lines.append(
            f"  {rel.nation_a.value.upper()} — {rel.nation_b.value.upper()}: "
            f"sentiment {rel.sentiment:+d}"
        )

    lines.append(f"\nREEF MARU: {state.reef_maru_status}")
    lines.append(f"STRAIT: {'Open' if state.strait_open else 'BLOCKADED'}")

    if state.active_effects:
        lines.append(f"\nACTIVE EFFECTS:")
        for effect in state.active_effects:
            lines.append(f"  - {effect}")

    lines.append(f"\n{'='*40}")
    lines.append("SUBMITTED ACTIONS:\n")

    for nation_name, turn_actions in ctx.all_actions.items():
        lines.append(f"--- {nation_name.value.upper()} ---")
        for i, action in enumerate(turn_actions.actions, 1):
            visibility = action.visibility.value.upper()
            target = f" (target: {action.target.value})" if action.target else ""
            lines.append(
                f"  {i}. [{visibility}] [{action.category}]{target}: "
                f"{action.description}"
            )
        lines.append("")

    if ctx.history:
        lines.append("PREVIOUS TURNS:")
        for entry in ctx.history:
            lines.append(f"  {entry}")
        lines.append("")

    lines.append(
        f"Turns since last event injection: {ctx.turns_since_last_event}\n"
    )

    # Rule engine context
    if ctx.econ_changes:
        lines.append("PRE-APPLIED ECONOMIC ADJUSTMENTS (already reflected in state above):")
        for nation in NationName:
            deltas = ctx.econ_changes.get(nation, {})
            if deltas:
                parts = [f"{k} {v:+d}" for k, v in deltas.items()]
                lines.append(f"  {nation.value.upper()}: {', '.join(parts)}")
        lines.append("")

    if ctx.applied_costs:
        lines.append("PRE-APPLIED ACTION COSTS (already reflected in state above):")
        for ac in ctx.applied_costs:
            changes_parts = []
            for nation, deltas in ac.resource_changes.items():
                for k, v in deltas.items():
                    changes_parts.append(f"{k} {v:+d}")
            cost_str = ", ".join(changes_parts) if changes_parts else "no resource change"
            lines.append(
                f"  {ac.nation.value.upper()} — {ac.action.description}: {cost_str}"
            )
        lines.append("")

    if ctx.unmatched_actions:
        lines.append("ACTIONS REQUIRING YOUR RESOLUTION (costs NOT pre-applied):")
        for nation, action in ctx.unmatched_actions:
            target = f" (target: {action.target.value})" if action.target else ""
            lines.append(
                f"  {nation.value.upper()} — [{action.visibility.value.upper()}] "
                f"[{action.category}]{target}: {action.description}"
            )
        lines.append("")

    lines.append(
        "Resolve all actions simultaneously. The rule engine has already "
        "applied economic adjustments and standard action costs — do NOT "
        "re-emit changes for those. Emit `resource` changes for unmatched "
        "actions and second-order effects, `relationship` changes as "
        "warranted, and `resource` changes that net out a pre-applied "
        "cost if any action is invalid in context (cite the action in "
        "`reason`). Detect secret actions via skill_roll. Inject a world "
        "event if appropriate. Return `narrative`, `action_results`, "
        "`changes`, and optionally `event_injected` / `private_intel`."
    )

    return "\n".join(lines)


def build_summary_prompt(state: WorldState, history: list[str]) -> str:
    """Build the prompt for generating the final game summary."""
    lines = [
        "=== GAME OVER ===\n",
        f"The game lasted {state.turn} turns.\n",
        "FINAL STATE:",
    ]

    for name, ns in state.nations.items():
        lines.append(
            f"  {name.value.upper()}: Military={ns.resources.military}, "
            f"Treasury={ns.resources.treasury}, Food={ns.resources.food}, "
            f"Support={ns.resources.support}"
        )

    lines.append(f"\nREEF MARU: {state.reef_maru_status}")

    lines.append(f"\nFULL HISTORY:")
    for entry in history:
        lines.append(f"  {entry}")

    lines.append(
        "\nProvide a final narrative summary and assessment. Evaluate each "
        "nation on: sovereignty outcome, resource position vs starting values, "
        "stability (public support), and alliances built or burned. "
        "Who came out ahead? What were the turning points?"
    )

    return "\n".join(lines)
