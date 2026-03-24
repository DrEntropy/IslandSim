from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from islandsim.config import ACTION_MENU, ECONOMIC_RULES
from islandsim.models import NationName

if TYPE_CHECKING:
    from islandsim.agents import FacilitatorContext, NationContext


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
Three island-nations (Naru, Veldara, Tauma) face a crisis over Reef Maru — a \
small uninhabited atoll where a massive rare earth deposit has been discovered. \
All three have overlapping sovereignty claims. The geography forces all major \
shipping through the Naru Strait (two deep-water channels flanking Naru). A \
severe typhoon season is forecast.

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

NARU_SYSTEM_PROMPT = _COUNTRY_BASE.format(
    name="Naru",
    traits=(
        "Naru is a small island controlling the only two navigable channels "
        "(North and South Channel) through the strait. You have strong coast "
        "guard/navy relative to your size, and your treasury is healthy from "
        "toll revenue. However, you are critically dependent on food imports — "
        "if trade stops, your people starve. Your population is small. You are "
        "pragmatic and transactional, historically neutral. The strait is both "
        "your greatest asset and greatest vulnerability."
    ),
    economic_rules=ECONOMIC_RULES,
    action_menu=ACTION_MENU,
)

VELDARA_SYSTEM_PROMPT = _COUNTRY_BASE.format(
    name="Veldara",
    traits=(
        "Veldara is the largest island, lying to the east. You have rich "
        "mineral deposits (rare earths critical for tech manufacturing), "
        "fertile farmland, and the largest population. Your navy is weak. "
        "Your mining regions are inland and need port access through the "
        "Naru Strait to reach export markets. Internal politics are tense "
        "between mining interests and farming communities. You see yourself "
        "as the natural regional leader — confident, sometimes overreaching."
    ),
    economic_rules=ECONOMIC_RULES,
    action_menu=ACTION_MENU,
)

TAUMA_SYSTEM_PROMPT = _COUNTRY_BASE.format(
    name="Tauma",
    traits=(
        "Tauma is an archipelago of smaller islands in the open ocean to the "
        "west. You have the best navy in the region, deep natural harbors, "
        "skilled shipbuilders, and a strong maritime tradition. However, you "
        "lack natural resources beyond fish — no rare earths, poor farming "
        "soil. You depend on Veldara for minerals and manufactured goods, all "
        "of which must transit through the Naru Strait. You are proud, "
        "independent, and suspicious of Veldara's ambitions. Historical "
        "rivalry with Veldara."
    ),
    economic_rules=ECONOMIC_RULES,
    action_menu=ACTION_MENU,
)

COUNTRY_PROMPTS = {
    NationName.NARU: NARU_SYSTEM_PROMPT,
    NationName.VELDARA: VELDARA_SYSTEM_PROMPT,
    NationName.TAUMA: TAUMA_SYSTEM_PROMPT,
}

# ---------------------------------------------------------------------------
# Facilitator system prompt
# ---------------------------------------------------------------------------

FACILITATOR_SYSTEM_PROMPT = f"""\
You are the Facilitator (game master) for a multi-turn tabletop exercise \
involving three island-nations: Naru, Veldara, and Tauma. They are competing \
and negotiating over Reef Maru, a disputed atoll with massive rare earth deposits.

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
{ECONOMIC_RULES}

ACTION REFERENCE:
{ACTION_MENU}

RELATIONSHIP TRACKING:
Track sentiment between each pair of nations. Hostile actions decrease \
sentiment; cooperation increases it. Major betrayals cause large drops.

EVENT INJECTION:
Every 2-3 turns, inject a world event to prevent stalemate and test \
adaptability. Examples: typhoon hits shipping lanes, pirate activity, a \
journalist leaks a secret deal, a foreign power expresses interest in \
the region, fishing stocks collapse, refugee crisis.

RESOLUTION GUIDELINES:
- Apply the listed resource costs for straightforward actions.
- For secret actions: determine if they are detected based on context \
(target's espionage investment, the action's inherent risk of exposure, etc.).
- Resource values must stay in 0-100 range. Clamp if needed.
- If a nation's Food drops below 20, apply unrest penalties to Support.
- If Support drops below 25, note government instability.
- Be specific about resource changes — state exact numbers.
- The narrative should be engaging and read like a news briefing.
"""

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

    lines.append(
        "Resolve all actions simultaneously. Apply resource costs/gains, "
        "determine outcomes for ambiguous actions, detect secret actions where "
        "appropriate, and update the world state. Apply per-turn economic "
        "adjustments (income and food production/consumption) BEFORE action "
        "resolution. Inject a world event if appropriate (every 2-3 turns). "
        "Return the complete updated world state."
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
