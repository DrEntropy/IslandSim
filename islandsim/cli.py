"""Human-playable CLI for IslandSim.

Provides rich terminal display and input functions so a human can control
one nation while the other two remain AI-driven.  All functions are
synchronous (called from within ``asyncio.to_thread``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from islandsim.models import (
    Action,
    ActionVisibility,
    GameSummary,
    NationName,
    Resources,
    StandardActionType,
    TurnActions,
    TurnResolution,
    WorldState,
)
from islandsim.scenario import ACTION_CATEGORIES, ACTION_LABELS

if TYPE_CHECKING:
    from islandsim.rules import ActionCost
    from islandsim.scenario import ScenarioConfig

console = Console()

# Actions that require a target nation
_TARGET_ACTIONS = {
    StandardActionType.NAVAL_BLOCKADE,
    StandardActionType.TRADE_SANCTIONS,
    StandardActionType.ECONOMIC_AID,
    StandardActionType.ESPIONAGE,
}

# Category display order
_CATEGORY_ORDER = ["MILITARY", "ECONOMIC", "DIPLOMATIC", "DOMESTIC"]


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------


def _resource_color(field: str, value: int) -> str:
    """Return a color string for a resource value based on thresholds."""
    if field == "food":
        if value < 10:
            return "red"
        if value < 20:
            return "yellow"
    if field == "support":
        if value < 25:
            return "red"
        if value < 40:
            return "yellow"
    if value < 15:
        return "red"
    if value < 30:
        return "yellow"
    return "green"


def _compute_remaining_resources(
    base: Resources,
    actions_so_far: list[Action],
    action_costs: dict[StandardActionType, ActionCost],
) -> Resources:
    """Compute resources remaining after already-queued standard actions."""
    remaining = base.model_copy()
    for action in actions_so_far:
        if action.action_type is None:
            continue
        cost_def = action_costs.get(action.action_type)
        if not cost_def:
            continue
        for field, delta in cost_def.actor.items():
            current = getattr(remaining, field)
            setattr(remaining, field, max(0, current + delta))
    return remaining


def _is_affordable(
    cost_actor: dict[str, int], remaining: Resources,
) -> bool:
    """Check if an action is affordable given remaining resources."""
    for field, delta in cost_actor.items():
        if getattr(remaining, field) + delta < 0:
            return False
    return True


def _format_cost(cost_actor: dict[str, int], cost_target: dict[str, int] | None) -> str:
    """Format action cost as a human-readable string."""
    parts = []
    short = {"military": "Mil", "treasury": "Tre", "food": "Food", "support": "Sup"}
    for resource, delta in cost_actor.items():
        parts.append(f"{delta:+d} {short.get(resource, resource)}")
    if cost_target:
        for resource, delta in cost_target.items():
            parts.append(f"{delta:+d} target {short.get(resource, resource)}")
    return ", ".join(parts) if parts else "free"


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------


def display_turn_header(turn: int, max_turns: int) -> None:
    console.print()
    console.print(Rule(f"[bold]TURN {turn} of {max_turns}[/bold]", style="bright_blue"))
    console.print()


def display_resources(nation: NationName, world_state: WorldState) -> None:
    ns = world_state.nations[nation]
    table = Table(title=f"Your Resources ({nation.value.upper()})", show_lines=False)
    for field in ("military", "treasury", "food", "support"):
        val = getattr(ns.resources, field)
        color = _resource_color(field, val)
        table.add_column(field.capitalize(), justify="center", style=color)
    table.add_row(
        str(ns.resources.military),
        str(ns.resources.treasury),
        str(ns.resources.food),
        str(ns.resources.support),
    )
    console.print(table)


def display_other_nations(nation: NationName, world_state: WorldState) -> None:
    table = Table(title="Other Nations", show_lines=True)
    table.add_column("Nation", style="bold")
    table.add_column("Military", justify="center")
    table.add_column("Treasury", justify="center")
    table.add_column("Food", justify="center")
    table.add_column("Support", justify="center")
    for n in NationName:
        if n == nation:
            continue
        r = world_state.nations[n].resources
        table.add_row(n.value.upper(), str(r.military), str(r.treasury), str(r.food), str(r.support))
    console.print(table)


def display_relationships(world_state: WorldState) -> None:
    lines: list[str] = []
    for rel in world_state.relationships:
        val = rel.sentiment
        if val > 0:
            color = "green"
        elif val < 0:
            color = "red"
        else:
            color = "dim"
        lines.append(
            f"  [{color}]{rel.nation_a.value.upper()} — {rel.nation_b.value.upper()}: "
            f"{val:+d}[/{color}]"
        )
    console.print(Panel("\n".join(lines), title="Relationships", border_style="dim"))


def display_world_status(world_state: WorldState) -> None:
    lines: list[str] = []
    lines.append(f"Reef Maru: {world_state.reef_maru_status}")
    strait = "[green]OPEN[/green]" if world_state.strait_open else "[red]BLOCKADED[/red]"
    lines.append(f"Naru Strait: {strait}")
    if world_state.active_effects:
        lines.append("")
        lines.append("[bold]Active Effects:[/bold]")
        for effect in world_state.active_effects:
            lines.append(f"  - {effect}")
    console.print(Panel("\n".join(lines), title="World Status", border_style="blue"))


def display_history(history: list[str]) -> None:
    if not history:
        return
    # Show last 5 turns, or all if fewer
    recent = history[-5:]
    console.print(Panel("\n\n".join(recent), title="Recent History", border_style="dim"))


def display_private_intel(intel: list[str]) -> None:
    if not intel:
        return
    lines = [f"  - {item}" for item in intel]
    console.print(Panel(
        "\n".join(lines),
        title="PRIVATE INTELLIGENCE (only you know this)",
        border_style="cyan",
    ))


def display_game_state(
    nation: NationName,
    world_state: WorldState,
    history: list[str],
    private_intel: list[str],
) -> None:
    """Full situation briefing at the start of a turn."""
    display_resources(nation, world_state)
    console.print()
    display_other_nations(nation, world_state)
    console.print()
    display_relationships(world_state)
    console.print()
    display_world_status(world_state)
    console.print()
    display_history(history)
    display_private_intel(intel=private_intel)


def display_action_menu(
    scenario: ScenarioConfig,
    remaining: Resources,
) -> list[tuple[int, StandardActionType, str, dict[str, int], dict[str, int] | None, bool, bool]]:
    """Display the numbered action menu and return the menu items.

    Returns list of (menu_number, action_type, label, actor_cost, target_cost,
    affordable, requires_strait).
    """
    action_costs = scenario.get_action_costs()
    menu_items: list[tuple[int, StandardActionType, str, dict[str, int], dict[str, int] | None, bool, bool]] = []
    num = 1

    for category in _CATEGORY_ORDER:
        cat_items: list[str] = []
        for key, cfg in scenario.action_costs.items():
            if ACTION_CATEGORIES.get(key) != category:
                continue
            action_type = StandardActionType(key)
            label = ACTION_LABELS.get(key, key.replace("_", " ").title())
            cost_def = action_costs[action_type]
            affordable = _is_affordable(cost_def.actor, remaining)
            target_cost = dict(cost_def.target) if cost_def.target else None
            menu_items.append((num, action_type, label, dict(cost_def.actor), target_cost, affordable, cost_def.requires_strait))

            cost_str = _format_cost(cost_def.actor, target_cost)
            if cost_def.requires_strait:
                cost_str += " [dim](needs strait)[/dim]"
            tag = "[green]OK[/green]" if affordable else "[red]$$[/red]"
            cat_items.append(f"  [bold]{num:>2}[/bold]. {label}  [dim]({cost_str})[/dim]  {tag}")
            num += 1

        if cat_items:
            console.print(f"\n[bold underline]{category}[/bold underline]")
            for line in cat_items:
                console.print(line)

    console.print(f"\n [bold]{num:>2}[/bold]. [italic]Custom action (free text)[/italic]")
    console.print(f"  [bold] 0[/bold]. Done — submit actions\n")

    return menu_items


def display_action_summary(actions: list[Action]) -> None:
    if not actions:
        return
    table = Table(title="Your Actions", show_lines=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("Description")
    table.add_column("Visibility", justify="center")
    table.add_column("Target", justify="center")
    table.add_column("Type", justify="center")
    for i, action in enumerate(actions, 1):
        vis_style = "yellow" if action.visibility == ActionVisibility.SECRET else ""
        target_str = action.target.value.upper() if action.target else "—"
        type_str = action.action_type.value if action.action_type else "custom"
        table.add_row(
            str(i),
            action.description,
            Text(action.visibility.value.upper(), style=vis_style),
            target_str,
            type_str,
        )
    console.print(table)


def display_turn_resolution(
    resolution: TurnResolution,
    player_nation: NationName,
    prev_state: WorldState,
) -> None:
    """Display the facilitator's turn results for the human player."""
    console.print()
    console.print(Rule("[bold]TURN RESULTS[/bold]", style="bright_yellow"))
    console.print()

    # Narrative
    console.print(Panel(resolution.narrative, title="What Happened", border_style="yellow"))

    # Event injection
    if resolution.event_injected:
        console.print(Panel(
            resolution.event_injected,
            title="WORLD EVENT",
            border_style="red bold",
        ))

    # Resource changes for the player
    prev_r = prev_state.nations[player_nation].resources
    new_r = resolution.updated_state.nations[player_nation].resources
    table = Table(title=f"Resource Changes ({player_nation.value.upper()})", show_lines=False)
    table.add_column("Resource", style="bold")
    table.add_column("Before", justify="center")
    table.add_column("After", justify="center")
    table.add_column("Delta", justify="center")
    for field in ("military", "treasury", "food", "support"):
        before = getattr(prev_r, field)
        after = getattr(new_r, field)
        delta = after - before
        delta_color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
        table.add_row(
            field.capitalize(),
            str(before),
            str(after),
            Text(f"{delta:+d}", style=delta_color),
        )
    console.print(table)

    # New private intel
    nation_intel = resolution.private_intel.get(player_nation, [])
    if nation_intel:
        lines = [f"  - {item}" for item in nation_intel]
        console.print(Panel(
            "\n".join(lines),
            title="NEW INTELLIGENCE",
            border_style="cyan",
        ))
    console.print()


def display_game_summary(summary: GameSummary) -> None:
    console.print()
    console.print(Rule("[bold]GAME OVER[/bold]", style="bright_red"))
    console.print()
    console.print(Panel(summary.narrative, title="Final Summary", border_style="bright_red"))
    console.print(Panel(summary.reef_maru_outcome, title="Reef Maru Outcome", border_style="blue"))
    for nation, assessment in summary.nation_assessments.items():
        console.print(Panel(assessment, title=nation.value.upper(), border_style="dim"))


# ---------------------------------------------------------------------------
# Input functions
# ---------------------------------------------------------------------------


def _prompt_visibility() -> ActionVisibility:
    while True:
        choice = console.input("[dim](1=Public, 2=Secret)[/dim] Visibility [bold][1][/bold]: ").strip()
        if choice in ("", "1"):
            return ActionVisibility.PUBLIC
        if choice == "2":
            return ActionVisibility.SECRET
        console.print("[red]Invalid choice. Enter 1 or 2.[/red]")


def _prompt_target(player: NationName) -> NationName | None:
    others = [n for n in NationName if n != player]
    console.print("  Target nation:")
    for i, n in enumerate(others, 1):
        console.print(f"    {i}. {n.value.upper()}")
    console.print(f"    0. No target")
    while True:
        choice = console.input("  Target [bold][0][/bold]: ").strip()
        if choice in ("", "0"):
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(others):
                return others[idx]
        except ValueError:
            pass
        console.print("[red]Invalid choice.[/red]")


def prompt_action(
    scenario: ScenarioConfig,
    nation: NationName,
    remaining: Resources,
    actions_so_far: list[Action],
) -> Action | None:
    """Prompt the human for a single action. Returns None when done."""
    action_costs = scenario.get_action_costs()
    menu_items = display_action_menu(scenario, remaining)
    custom_num = len(menu_items) + 1
    count = len(actions_so_far)
    max_actions = 3

    console.print(f"[dim]Actions submitted: {count}/{max_actions}[/dim]")

    while True:
        choice = console.input(f"Choose action [bold][1-{custom_num}, or 0 to finish][/bold]: ").strip()
        try:
            num = int(choice)
        except ValueError:
            console.print("[red]Enter a number.[/red]")
            continue

        if num == 0:
            return None

        if num == custom_num:
            # Custom action
            description = console.input("Describe your action: ").strip()
            if not description:
                console.print("[red]Description cannot be empty.[/red]")
                continue
            console.print("Category: (1) military  (2) economic  (3) diplomatic  (4) domestic")
            cat_map = {"1": "military", "2": "economic", "3": "diplomatic", "4": "domestic"}
            while True:
                cat_choice = console.input("Category [bold][1][/bold]: ").strip()
                category = cat_map.get(cat_choice or "1")
                if category:
                    break
                console.print("[red]Enter 1-4.[/red]")
            visibility = _prompt_visibility()
            target = _prompt_target(nation)
            return Action(
                description=description,
                visibility=visibility,
                target=target,
                category=category,
                action_type=None,
            )

        # Standard action
        match = [item for item in menu_items if item[0] == num]
        if not match:
            console.print(f"[red]Enter a number between 0 and {custom_num}.[/red]")
            continue

        _, action_type, label, actor_cost, target_cost, affordable, requires_strait = match[0]

        if not affordable:
            console.print(f"[yellow]Warning: You may not have enough resources for this action.[/yellow]")
            confirm = console.input("Proceed anyway? [bold][y/n][/bold]: ").strip().lower()
            if confirm not in ("y", "yes", ""):
                continue

        if requires_strait and not True:  # strait status checked elsewhere
            pass

        # Description — pre-filled default
        desc_input = console.input(f"Description [bold][{label}][/bold]: ").strip()
        description = desc_input if desc_input else label

        visibility = _prompt_visibility()

        # Target — auto-prompt for actions that need one
        if action_type in _TARGET_ACTIONS:
            console.print("[dim]This action benefits from a target nation.[/dim]")
            target = _prompt_target(nation)
        else:
            target = None

        category = ACTION_CATEGORIES.get(action_type.value, "military").lower()
        return Action(
            description=description,
            visibility=visibility,
            target=target,
            category=category,
            action_type=action_type,
        )


def collect_human_actions(
    nation: NationName,
    world_state: WorldState,
    history: list[str],
    private_intel: list[str],
    scenario: ScenarioConfig,
) -> TurnActions:
    """Synchronous CLI loop to collect the human player's actions for one turn."""
    display_turn_header(world_state.turn, world_state.max_turns)
    display_game_state(nation, world_state, history, private_intel)

    action_costs = scenario.get_action_costs()
    actions: list[Action] = []

    while len(actions) < 3:
        remaining = _compute_remaining_resources(
            world_state.nations[nation].resources, actions, action_costs,
        )
        action = prompt_action(scenario, nation, remaining, actions)
        if action is None:
            if not actions:
                console.print("[red]You must submit at least 1 action.[/red]")
                continue
            break
        actions.append(action)
        console.print(f"[green]Action {len(actions)} added.[/green]")
        display_action_summary(actions)

        if len(actions) == 3:
            console.print("[dim]Maximum 3 actions reached.[/dim]")

    # Confirmation
    while True:
        display_action_summary(actions)
        confirm = console.input("Submit these actions? [bold](y/edit/cancel)[/bold]: ").strip().lower()
        if confirm in ("y", "yes", ""):
            break
        if confirm in ("cancel",):
            actions.clear()
            console.print("[yellow]Actions cleared. Start over.[/yellow]")
            # Re-collect
            while len(actions) < 3:
                remaining = _compute_remaining_resources(
                    world_state.nations[nation].resources, actions, action_costs,
                )
                action = prompt_action(scenario, nation, remaining, actions)
                if action is None:
                    if not actions:
                        console.print("[red]You must submit at least 1 action.[/red]")
                        continue
                    break
                actions.append(action)
                console.print(f"[green]Action {len(actions)} added.[/green]")
                display_action_summary(actions)
                if len(actions) == 3:
                    console.print("[dim]Maximum 3 actions reached.[/dim]")
        elif confirm == "edit":
            # Remove last action
            if actions:
                removed = actions.pop()
                console.print(f"[yellow]Removed: {removed.description}[/yellow]")
            # Let them add more
            while len(actions) < 3:
                remaining = _compute_remaining_resources(
                    world_state.nations[nation].resources, actions, action_costs,
                )
                action = prompt_action(scenario, nation, remaining, actions)
                if action is None:
                    if not actions:
                        console.print("[red]You must submit at least 1 action.[/red]")
                        continue
                    break
                actions.append(action)
                console.print(f"[green]Action {len(actions)} added.[/green]")
                display_action_summary(actions)
                if len(actions) == 3:
                    console.print("[dim]Maximum 3 actions reached.[/dim]")
        else:
            console.print("[red]Enter y, edit, or cancel.[/red]")

    reasoning = console.input("Strategic reasoning (private, not shared): ").strip()
    if not reasoning:
        reasoning = "No reasoning provided."

    return TurnActions(nation=nation, actions=actions, reasoning=reasoning)


# ---------------------------------------------------------------------------
# Async wrapper
# ---------------------------------------------------------------------------


async def run_human_turn(
    nation: NationName,
    world_state: WorldState,
    history: list[str],
    private_intel: list[str],
    scenario: ScenarioConfig,
) -> TurnActions:
    """Async wrapper around the synchronous CLI input loop."""
    return await asyncio.to_thread(
        collect_human_actions, nation, world_state, history, private_intel, scenario,
    )
