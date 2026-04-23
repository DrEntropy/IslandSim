"""Textual TUI for the human player.

A single long-lived :class:`GameApp` drives the whole session so the player
never drops back to the terminal between phases.  Screens rotate via
``switch_screen``::

    Briefing → Waiting → Resolution → Briefing → … → Waiting → Summary

Public entry point: :func:`run_game_tui`, called from ``islandsim.game``
when ``human_nation`` is set.
"""

from __future__ import annotations

import asyncio
import datetime
import random
from typing import TYPE_CHECKING

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    RadioButton,
    RadioSet,
    Static,
    TabbedContent,
    TabPane,
)

from islandsim.models import (
    Action,
    ActionVisibility,
    GameLog,
    GameSummary,
    NationName,
    Resources,
    RunMetadata,
    StandardActionType,
    TurnActions,
    TurnRecord,
    TurnResolution,
    WorldState,
)
from islandsim.scenario import ACTION_CATEGORIES, ACTION_LABELS

if TYPE_CHECKING:
    from islandsim.rules import ActionCost
    from islandsim.scenario import ScenarioConfig


_TARGET_ACTIONS = {
    StandardActionType.NAVAL_BLOCKADE,
    StandardActionType.TRADE_SANCTIONS,
    StandardActionType.ECONOMIC_AID,
    StandardActionType.ESPIONAGE,
}

_CATEGORY_ORDER = ["MILITARY", "ECONOMIC", "DIPLOMATIC", "DOMESTIC"]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _resource_style(field: str, value: int) -> str:
    if field == "food":
        if value < 10:
            return "bold red"
        if value < 20:
            return "yellow"
    if field == "support":
        if value < 25:
            return "bold red"
        if value < 40:
            return "yellow"
    if value < 15:
        return "bold red"
    if value < 30:
        return "yellow"
    return "green"


def _format_cost(cost_actor: dict[str, int], cost_target: dict[str, int] | None) -> str:
    short = {"military": "Mil", "treasury": "Tre", "food": "Food", "support": "Sup"}
    parts = [f"{d:+d} {short.get(r, r)}" for r, d in cost_actor.items()]
    if cost_target:
        parts += [f"{d:+d} tgt {short.get(r, r)}" for r, d in cost_target.items()]
    return ", ".join(parts) if parts else "free"


def _is_affordable(cost_actor: dict[str, int], remaining: Resources) -> bool:
    for field, delta in cost_actor.items():
        if getattr(remaining, field) + delta < 0:
            return False
    return True


def _compute_remaining(
    base: Resources,
    actions: list[Action],
    action_costs: dict[StandardActionType, "ActionCost"],
) -> Resources:
    remaining = base.model_copy()
    for action in actions:
        if action.action_type is None:
            continue
        cost_def = action_costs.get(action.action_type)
        if not cost_def:
            continue
        for field, delta in cost_def.actor.items():
            current = getattr(remaining, field)
            setattr(remaining, field, max(0, current + delta))
    return remaining


def _resources_markup(
    nation: NationName,
    resources: Resources,
    intel_skill: int | None = None,
) -> str:
    lines = [f"[bold]{nation.value.upper()}[/]", ""]
    for field in ("military", "treasury", "food", "support"):
        val = getattr(resources, field)
        style = _resource_style(field, val)
        filled = val // 10
        bar = "█" * filled + "·" * (10 - filled)
        lines.append(f"[{style}]{field.capitalize():<9} {val:>3}  {bar}[/]")
    if intel_skill is not None:
        filled = intel_skill // 10
        bar = "█" * filled + "·" * (10 - filled)
        lines.append(f"[dim]Intel     {intel_skill:>3}  {bar}[/]")
    return "\n".join(lines)


def _others_markup(player: NationName, state: WorldState) -> str:
    lines = [f"[bold]{'Nation':<10} {'Mil':>4} {'Tre':>4} {'Food':>4} {'Sup':>4}[/]"]
    for n in NationName:
        if n == player:
            continue
        r = state.nations[n].resources
        lines.append(
            f"{n.value.upper():<10} {r.military:>4} {r.treasury:>4} {r.food:>4} {r.support:>4}"
        )
    return "\n".join(lines)


def _relationships_markup(state: WorldState) -> str:
    lines = []
    for rel in state.relationships:
        v = rel.sentiment
        color = "green" if v > 0 else "red" if v < 0 else "dim"
        lines.append(
            f"[{color}]{rel.nation_a.value.upper()} — {rel.nation_b.value.upper()}: "
            f"{v:+d}[/]"
        )
    return "\n".join(lines) or "[dim](none)[/]"


def _world_markup(state: WorldState) -> str:
    lines = [f"Reef Maru: {state.reef_maru_status}"]
    strait = "[green]OPEN[/]" if state.strait_open else "[red]BLOCKADED[/]"
    lines.append(f"Naru Strait: {strait}")
    if state.active_effects:
        lines.append("")
        lines.append("[bold]Active Effects:[/]")
        for e in state.active_effects:
            lines.append(f"  • {e}")
    return "\n".join(lines)


def _history_markup(history: list[str]) -> str:
    if not history:
        return "[dim](no history yet)[/]"
    return "\n\n".join(history[-5:])


def _intel_markup(intel: list[str]) -> str:
    if not intel:
        return "[dim](no private intel yet)[/]"
    return "\n".join(f"• {item}" for item in intel)


def _delta_markup(prev: Resources, new: Resources) -> str:
    lines = [f"[bold]{'Resource':<10} {'Before':>7} {'After':>7} {'Delta':>7}[/]"]
    for field in ("military", "treasury", "food", "support"):
        before = getattr(prev, field)
        after = getattr(new, field)
        delta = after - before
        dc = "green" if delta > 0 else "red" if delta < 0 else "dim"
        lines.append(
            f"{field.capitalize():<10} {before:>7} {after:>7}  [{dc}]{delta:+d}[/]"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Modals
# ---------------------------------------------------------------------------

_MODAL_CSS = """
ModalScreen {
    align: center middle;
}
#modal-box {
    background: $panel;
    border: thick $accent;
    padding: 1 2;
    width: 72;
    height: auto;
}
.modal-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
.buttons {
    height: auto;
    align: right middle;
    margin-top: 1;
}
Button { margin: 0 1; }
"""


class ActionDetailModal(ModalScreen[Action | None]):
    """Configure a standard action: description / visibility / target."""

    CSS = _MODAL_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        player: NationName,
        action_type: StandardActionType,
        default_description: str,
        cost_actor: dict[str, int],
        cost_target: dict[str, int] | None,
    ):
        super().__init__()
        self.player = player
        self.action_type = action_type
        self.default_description = default_description
        self.cost_actor = cost_actor
        self.cost_target = cost_target
        self.target_required = action_type in _TARGET_ACTIONS

    def compose(self) -> ComposeResult:
        others = [n for n in NationName if n != self.player]
        with Vertical(id="modal-box"):
            yield Static(f"[bold]{self.default_description}[/]", classes="modal-title")
            yield Static(f"Cost: {_format_cost(self.cost_actor, self.cost_target)}")
            yield Label("Description:")
            yield Input(value=self.default_description, id="desc-input")
            yield Label("Visibility:")
            with RadioSet(id="vis"):
                yield RadioButton("Public", value=True)
                yield RadioButton("Secret")
            label = "Target (required):" if self.target_required else "Target (optional):"
            yield Label(label)
            with RadioSet(id="target"):
                yield RadioButton("None", value=not self.target_required)
                for i, n in enumerate(others):
                    yield RadioButton(
                        n.value.upper(), value=self.target_required and i == 0
                    )
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Add", id="confirm", variant="primary")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#confirm")
    def _confirm(self) -> None:
        desc = (
            self.query_one("#desc-input", Input).value.strip()
            or self.default_description
        )
        vis_idx = self.query_one("#vis", RadioSet).pressed_index or 0
        visibility = ActionVisibility.PUBLIC if vis_idx == 0 else ActionVisibility.SECRET
        target_idx = self.query_one("#target", RadioSet).pressed_index or 0
        others = [n for n in NationName if n != self.player]
        target = others[target_idx - 1] if target_idx > 0 else None
        category = ACTION_CATEGORIES.get(self.action_type.value, "MILITARY").lower()
        self.dismiss(
            Action(
                description=desc,
                visibility=visibility,
                target=target,
                category=category,
                action_type=self.action_type,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class CustomActionModal(ModalScreen[Action | None]):
    """Free-text custom action."""

    CSS = _MODAL_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, player: NationName):
        super().__init__()
        self.player = player

    def compose(self) -> ComposeResult:
        others = [n for n in NationName if n != self.player]
        with Vertical(id="modal-box"):
            yield Static("[bold]Custom Action[/]", classes="modal-title")
            yield Label("Description:")
            yield Input(id="desc-input")
            yield Label("Category:")
            with RadioSet(id="cat"):
                yield RadioButton("Military", value=True)
                yield RadioButton("Economic")
                yield RadioButton("Diplomatic")
                yield RadioButton("Domestic")
            yield Label("Visibility:")
            with RadioSet(id="vis"):
                yield RadioButton("Public", value=True)
                yield RadioButton("Secret")
            yield Label("Target (optional):")
            with RadioSet(id="target"):
                yield RadioButton("None", value=True)
                for n in others:
                    yield RadioButton(n.value.upper())
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Add", id="confirm", variant="primary")

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#confirm")
    def _confirm(self) -> None:
        desc = self.query_one("#desc-input", Input).value.strip()
        if not desc:
            self.app.bell()
            return
        cats = ["military", "economic", "diplomatic", "domestic"]
        category = cats[self.query_one("#cat", RadioSet).pressed_index or 0]
        vis_idx = self.query_one("#vis", RadioSet).pressed_index or 0
        visibility = ActionVisibility.PUBLIC if vis_idx == 0 else ActionVisibility.SECRET
        target_idx = self.query_one("#target", RadioSet).pressed_index or 0
        others = [n for n in NationName if n != self.player]
        target = others[target_idx - 1] if target_idx > 0 else None
        self.dismiss(
            Action(
                description=desc,
                visibility=visibility,
                target=target,
                category=category,
                action_type=None,
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class ReasoningModal(ModalScreen[str]):
    """Ask the player for strategic reasoning after submit."""

    CSS = _MODAL_CSS
    BINDINGS = [Binding("escape", "skip", "Skip")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static("[bold]Strategic Reasoning[/]", classes="modal-title")
            yield Label("Recorded privately in the game log. Leave blank to skip.")
            yield Input(id="reasoning-input")
            with Horizontal(classes="buttons"):
                yield Button("Skip", id="skip")
                yield Button("Submit", id="submit", variant="primary")

    @on(Button.Pressed, "#skip")
    def _skip(self) -> None:
        self.dismiss("No reasoning provided.")

    @on(Button.Pressed, "#submit")
    def _submit(self) -> None:
        val = self.query_one("#reasoning-input", Input).value.strip()
        self.dismiss(val or "No reasoning provided.")

    def action_skip(self) -> None:
        self.dismiss("No reasoning provided.")


# ---------------------------------------------------------------------------
# List items
# ---------------------------------------------------------------------------


class ActionChoiceItem(ListItem):
    """One row in the action menu, bound to a standard action type."""

    def __init__(
        self,
        action_type: StandardActionType,
        label_text: str,
        cost_str: str,
        affordable: bool,
        requires_strait: bool,
    ):
        tag = "[green]✓[/]" if affordable else "[red]✗[/]"
        strait = "  [dim](needs strait)[/]" if requires_strait else ""
        display = f"{tag} {label_text}  [dim]({cost_str})[/]{strait}"
        super().__init__(Label(display))
        self.action_type = action_type
        self.label_text = label_text


class QueuedActionItem(ListItem):
    def __init__(self, index: int, action: Action):
        vis = action.visibility.value.upper()
        vis_color = "yellow" if action.visibility == ActionVisibility.SECRET else "cyan"
        target = action.target.value.upper() if action.target else "—"
        type_tag = action.action_type.value if action.action_type else "custom"
        display = (
            f"{index}. [{vis_color}]{vis}[/]  {action.description}  "
            f"[dim]({type_tag}, target: {target})[/]"
        )
        super().__init__(Label(display))


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


_BRIEFING_CSS = """
Screen { background: $surface; }

#main { layout: vertical; height: 1fr; }

#top-row, #mid-row { layout: horizontal; height: auto; }
#bottom-row { layout: horizontal; height: 1fr; }

.panel { border: round $primary; padding: 0 1; }
.panel-title { text-style: bold; color: $accent; }

#resources-panel { width: 42; height: 10; }
#others-panel { width: 1fr; height: 10; }
#rel-panel { width: 42; height: 8; }
#world-panel { width: 1fr; height: 8; }
#ctx-panel { width: 1fr; }
#action-panel { width: 62; }

#cat-buttons { height: 3; }
#cat-buttons Button { min-width: 12; margin: 0 1 0 0; }

#action-list { height: 10; border: round $primary-lighten-2; }
#queued-list { height: 6; border: round $primary-lighten-2; }

#action-buttons { height: 3; align: center middle; }
#action-buttons Button { margin: 0 1; }

#title-bar {
    height: 1;
    content-align: center middle;
    background: $accent;
    color: $text;
    text-style: bold;
}
"""


class BriefingScreen(Screen):
    """Per-turn briefing + action builder.  On submit notifies the app."""

    CSS = _BRIEFING_CSS

    def __init__(
        self,
        nation: NationName,
        state: WorldState,
        history: list[str],
        private_intel: list[str],
        scenario: "ScenarioConfig",
    ):
        super().__init__()
        self.nation = nation
        self.state = state
        self.history = history
        self.private_intel = private_intel
        self.scenario = scenario
        self.action_costs = scenario.get_action_costs()
        self.queued_actions: list[Action] = []
        self.current_category = "MILITARY"

    def compose(self) -> ComposeResult:
        with Vertical(id="main"):
            yield Static(
                f"IslandSim — Turn {self.state.turn}/{self.state.max_turns} — "
                f"Playing {self.nation.value.upper()}",
                id="title-bar",
            )
            with Container(id="top-row"):
                with Container(id="resources-panel", classes="panel"):
                    own = self.state.nations[self.nation]
                    yield Static(
                        _resources_markup(
                            self.nation, own.resources, own.intel_skill
                        ),
                        id="resources-display",
                    )
                with Container(id="others-panel", classes="panel"):
                    yield Static(
                        _others_markup(self.nation, self.state), id="others-display"
                    )
            with Container(id="mid-row"):
                with Container(id="rel-panel", classes="panel"):
                    yield Static(_relationships_markup(self.state), id="rel-display")
                with Container(id="world-panel", classes="panel"):
                    yield Static(_world_markup(self.state), id="world-display")
            with Container(id="bottom-row"):
                with Container(id="ctx-panel", classes="panel"):
                    with TabbedContent():
                        with TabPane("History"):
                            yield VerticalScroll(Static(_history_markup(self.history)))
                        with TabPane("Private Intel"):
                            yield VerticalScroll(
                                Static(_intel_markup(self.private_intel))
                            )
                with Vertical(id="action-panel", classes="panel"):
                    yield Label("[bold]Build Actions (0/3)[/]", id="action-title")
                    with Horizontal(id="cat-buttons"):
                        for cat in _CATEGORY_ORDER:
                            yield Button(
                                cat.title(),
                                id=f"cat-{cat}",
                                variant=(
                                    "primary"
                                    if cat == self.current_category
                                    else "default"
                                ),
                            )
                    yield ListView(id="action-list")
                    with Horizontal(id="action-buttons"):
                        yield Button("Custom…", id="btn-custom")
                        yield Button("Remove Last", id="btn-remove")
                        yield Button("Submit", id="btn-submit", variant="success")
                    yield Label("[bold]Queued:[/]")
                    yield ListView(id="queued-list")
        yield Footer()

    def on_mount(self) -> None:
        self.app.title = (
            f"IslandSim — Turn {self.state.turn}/{self.state.max_turns} — "
            f"Playing {self.nation.value.upper()}"
        )
        self._refresh_action_list()
        # Focus action list so arrow keys + Enter work immediately.
        list_view = self.query_one("#action-list", ListView)
        list_view.focus()
        if len(list_view.children) > 0:
            list_view.index = 0

    # --- refresh ---

    def _refresh_action_list(self) -> None:
        remaining = _compute_remaining(
            self.state.nations[self.nation].resources,
            self.queued_actions,
            self.action_costs,
        )
        list_view = self.query_one("#action-list", ListView)
        list_view.clear()
        for key in self.scenario.action_costs:
            if ACTION_CATEGORIES.get(key) != self.current_category:
                continue
            action_type = StandardActionType(key)
            label_text = ACTION_LABELS.get(key, key.replace("_", " ").title())
            cost_def = self.action_costs[action_type]
            target_cost = dict(cost_def.target) if cost_def.target else None
            cost_str = _format_cost(dict(cost_def.actor), target_cost)
            affordable = _is_affordable(cost_def.actor, remaining)
            list_view.append(
                ActionChoiceItem(
                    action_type,
                    label_text,
                    cost_str,
                    affordable,
                    cost_def.requires_strait,
                )
            )

    def _refresh_queued(self) -> None:
        q = self.query_one("#queued-list", ListView)
        q.clear()
        for i, action in enumerate(self.queued_actions, 1):
            q.append(QueuedActionItem(i, action))
        self.query_one("#action-title", Label).update(
            f"[bold]Build Actions ({len(self.queued_actions)}/3)[/]"
        )

    def _on_action_added(self, action: Action | None) -> None:
        if action is None:
            return
        self.queued_actions.append(action)
        self._refresh_queued()
        self._refresh_action_list()

    # --- handlers ---

    @on(Button.Pressed, "#cat-MILITARY, #cat-ECONOMIC, #cat-DIPLOMATIC, #cat-DOMESTIC")
    def _change_category(self, event: Button.Pressed) -> None:
        cat = event.button.id.split("-", 1)[1]
        if cat != self.current_category:
            self.current_category = cat
            for c in _CATEGORY_ORDER:
                btn = self.query_one(f"#cat-{c}", Button)
                btn.variant = "primary" if c == cat else "default"
            self._refresh_action_list()
        list_view = self.query_one("#action-list", ListView)
        list_view.focus()
        if len(list_view.children) > 0:
            list_view.index = 0

    @on(ListView.Selected, "#action-list")
    def _action_chosen(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, ActionChoiceItem):
            return
        if len(self.queued_actions) >= 3:
            self.notify("Already at 3 actions.", severity="warning")
            return
        cost_def = self.action_costs[item.action_type]
        self.app.push_screen(
            ActionDetailModal(
                self.nation,
                item.action_type,
                item.label_text,
                dict(cost_def.actor),
                dict(cost_def.target) if cost_def.target else None,
            ),
            self._on_action_added,
        )

    @on(Button.Pressed, "#btn-custom")
    def _add_custom(self) -> None:
        if len(self.queued_actions) >= 3:
            self.notify("Already at 3 actions.", severity="warning")
            return
        self.app.push_screen(CustomActionModal(self.nation), self._on_action_added)

    @on(Button.Pressed, "#btn-remove")
    def _remove_last(self) -> None:
        if self.queued_actions:
            self.queued_actions.pop()
            self._refresh_queued()
            self._refresh_action_list()

    @on(Button.Pressed, "#btn-submit")
    def _submit(self) -> None:
        if not self.queued_actions:
            self.notify("You must submit at least one action.", severity="error")
            return

        def _finish(reasoning: str | None) -> None:
            actions = TurnActions(
                nation=self.nation,
                actions=list(self.queued_actions),
                reasoning=reasoning or "No reasoning provided.",
            )
            # Hand off to the app.
            self.app.briefing_complete(actions)

        self.app.push_screen(ReasoningModal(), _finish)


_WAITING_CSS = """
Screen { background: $surface; align: center middle; }

#waiting-box {
    width: 60;
    height: auto;
    padding: 2 3;
    border: round $accent;
    background: $panel;
}
#waiting-status {
    text-style: bold;
    color: $accent;
    content-align: center middle;
    width: 1fr;
    height: 3;
}
#waiting-hint {
    color: $text-muted;
    content-align: center middle;
    width: 1fr;
    margin-top: 1;
}
LoadingIndicator { height: 3; }
"""


class WaitingScreen(Screen):
    """Shown while the rule engine or facilitator is running."""

    CSS = _WAITING_CSS

    def __init__(self, status_text: str = "Working…"):
        super().__init__()
        self._status_text = status_text

    def compose(self) -> ComposeResult:
        with Container(id="waiting-box"):
            yield Static(self._status_text, id="waiting-status")
            yield LoadingIndicator()
            yield Static(
                "(facilitator LLM calls usually take 20–40 seconds)",
                id="waiting-hint",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.app.title = "IslandSim — Resolving…"

    def set_status(self, text: str) -> None:
        self._status_text = text
        try:
            self.query_one("#waiting-status", Static).update(text)
        except Exception:
            pass


_RESOLUTION_CSS = """
Screen { background: $surface; }
VerticalScroll { height: 1fr; min-height: 0; }
.panel { height: auto; border: round $primary; padding: 0 1; margin-bottom: 1; }
.narrative { border: round $warning; }
.event { border: thick $error; }
.intel { border: round $success; }
.delta { border: round $accent; }
#continue-bar { height: 3; align: center middle; dock: bottom; }
"""


class ResolutionScreen(Screen):
    """Shows the facilitator's turn resolution."""

    CSS = _RESOLUTION_CSS
    BINDINGS = [
        Binding("enter", "continue", "Continue"),
        Binding("space", "continue", "Continue"),
    ]

    def __init__(
        self,
        resolution: TurnResolution,
        player: NationName,
        prev_state: WorldState,
        final_state: WorldState,
    ):
        super().__init__()
        self.resolution = resolution
        self.player = player
        self.prev_state = prev_state
        self.final_state = final_state

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            with Container(classes="panel narrative"):
                yield Label("[bold]What Happened[/]")
                yield Static(self.resolution.narrative)
            if self.resolution.event_injected:
                with Container(classes="panel event"):
                    yield Label("[bold red]WORLD EVENT[/]")
                    yield Static(self.resolution.event_injected)
            with Container(classes="panel delta"):
                yield Label(
                    f"[bold]Resource Changes ({self.player.value.upper()})[/]"
                )
                prev_r = self.prev_state.nations[self.player].resources
                new_r = self.final_state.nations[self.player].resources
                yield Static(_delta_markup(prev_r, new_r))
            intel = self.resolution.private_intel.get(self.player, [])
            if intel:
                with Container(classes="panel intel"):
                    yield Label("[bold]New Intelligence[/]")
                    yield Static("\n".join(f"• {i}" for i in intel))
        with Container(id="continue-bar"):
            yield Button("Continue →", id="btn-continue", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.app.title = (
            f"Turn {self.final_state.turn} Results — "
            f"{self.player.value.upper()}"
        )
        self.query_one("#btn-continue", Button).focus()

    @on(Button.Pressed, "#btn-continue")
    def _continue(self) -> None:
        self.app.resolution_complete()

    def action_continue(self) -> None:
        self.app.resolution_complete()


_SUMMARY_CSS = """
Screen { background: $surface; }
VerticalScroll { height: 1fr; min-height: 0; }
.panel { height: auto; border: round $primary; padding: 0 1; margin-bottom: 1; }
#done-bar { height: 3; align: center middle; dock: bottom; }
"""


class SummaryScreen(Screen):
    """Final game-over screen."""

    CSS = _SUMMARY_CSS
    BINDINGS = [
        Binding("enter", "done", "Done"),
        Binding("q", "done", "Done"),
    ]

    def __init__(self, summary: GameSummary):
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            with Container(classes="panel"):
                yield Label("[bold red]GAME OVER[/]")
                yield Static(self.summary.narrative)
            with Container(classes="panel"):
                yield Label("[bold]Reef Maru Outcome[/]")
                yield Static(self.summary.reef_maru_outcome)
            for nation, assessment in self.summary.nation_assessments.items():
                with Container(classes="panel"):
                    yield Label(f"[bold]{nation.value.upper()}[/]")
                    yield Static(assessment)
        with Container(id="done-bar"):
            yield Button("Done", id="btn-done", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.app.title = "IslandSim — Game Over"
        self.query_one("#btn-done", Button).focus()

    @on(Button.Pressed, "#btn-done")
    def _done(self) -> None:
        self.app.summary_complete()

    def action_done(self) -> None:
        self.app.summary_complete()


# ---------------------------------------------------------------------------
# GameApp — long-lived app that drives the whole session
# ---------------------------------------------------------------------------


class GameApp(App[None]):
    """Long-lived app.  The game loop runs as a textual worker inside the
    app (so ``active_app`` is set in its context), driving screen transitions
    via the ``show_*`` async methods; screens call back via ``*_complete``
    to signal the user has finished with them."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        scenario_name: str,
        num_turns: int | None,
        human_nation: NationName,
        seed: int | None = None,
    ):
        super().__init__()
        self.scenario_name = scenario_name
        self.num_turns_arg = num_turns
        self.human_nation = human_nation
        self.seed = seed
        self.result: tuple[GameSummary, GameLog] | None = None
        self.game_error: BaseException | None = None
        self._briefing_future: asyncio.Future[TurnActions] | None = None
        self._continue_future: asyncio.Future[None] | None = None

    def on_mount(self) -> None:
        self.title = f"IslandSim — {self.human_nation.value.upper()}"
        self.push_screen(WaitingScreen("Starting game…"))
        # Game loop runs as a textual worker so it inherits the app's
        # context (active_app ContextVar is set, screens can mount, etc.).
        self.run_worker(self._game_loop(), name="game-loop", exclusive=True)

    # --- game-loop-facing async methods ---

    async def show_briefing(
        self,
        nation: NationName,
        state: WorldState,
        history: list[str],
        private_intel: list[str],
        scenario: "ScenarioConfig",
    ) -> TurnActions:
        self._briefing_future = asyncio.get_event_loop().create_future()
        self.switch_screen(BriefingScreen(nation, state, history, private_intel, scenario))
        return await self._briefing_future

    async def show_waiting(self, status: str) -> None:
        # Switch to a fresh WaitingScreen.  Fire-and-forget — game loop
        # continues with its heavy work while the user sees the spinner.
        self.switch_screen(WaitingScreen(status))
        # Yield once so the screen actually mounts before we proceed.
        await asyncio.sleep(0)

    async def show_resolution(
        self,
        resolution: TurnResolution,
        player: NationName,
        prev_state: WorldState,
        final_state: WorldState,
    ) -> None:
        self._continue_future = asyncio.get_event_loop().create_future()
        self.switch_screen(
            ResolutionScreen(resolution, player, prev_state, final_state)
        )
        await self._continue_future

    async def show_summary(self, summary: GameSummary) -> None:
        self._continue_future = asyncio.get_event_loop().create_future()
        self.switch_screen(SummaryScreen(summary))
        await self._continue_future

    # --- screen-facing completion callbacks ---

    def briefing_complete(self, actions: TurnActions) -> None:
        fut = self._briefing_future
        if fut is not None and not fut.done():
            fut.set_result(actions)

    def resolution_complete(self) -> None:
        fut = self._continue_future
        if fut is not None and not fut.done():
            fut.set_result(None)

    def summary_complete(self) -> None:
        fut = self._continue_future
        if fut is not None and not fut.done():
            fut.set_result(None)

    # --- game loop (runs as a textual worker) ---

    async def _game_loop(self) -> None:
        """The whole game, driven from inside the app's context."""
        from islandsim.agents import create_agents
        from islandsim.game import (
            generate_summary,
            resolve_turn,
            run_country_agent,
        )
        from islandsim.rules import (
            apply_action_costs,
            apply_changes,
            apply_economic_adjustments,
        )
        from islandsim.scenario import load_scenario
        from islandsim.settings import load_settings

        try:
            scenario = load_scenario(self.scenario_name)
            settings = load_settings()
            rng = random.Random(self.seed) if self.seed is not None else None
            country_agents, facilitator, summary_agent_inst = create_agents(
                scenario, settings, rng=rng,
            )

            state = scenario.to_starting_state()
            turns = (
                self.num_turns_arg
                if self.num_turns_arg is not None
                else settings.default_turns
            )
            state.max_turns = turns
            initial_state = state.model_copy(deep=True)
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            history: list[str] = []
            private_intel: dict[NationName, list[str]] = {n: [] for n in NationName}
            turn_records: list[TurnRecord] = []
            turns_since_event = 0

            for turn in range(1, turns + 1):
                state.turn = turn

                # Kick off AI country agents as background tasks so they run
                # concurrently with the human briefing.  Keeping them in
                # separate tasks (not asyncio.gather) means an AI failure
                # cannot cancel the briefing future mid-interaction.
                ai_tasks: dict[NationName, asyncio.Task[TurnActions]] = {}
                for nation in NationName:
                    if nation == self.human_nation:
                        continue
                    ai_tasks[nation] = asyncio.create_task(
                        run_country_agent(
                            nation,
                            state,
                            history,
                            private_intel[nation],
                            country_agents[nation],
                        ),
                        name=f"ai-{nation.value}-turn-{turn}",
                    )

                # Show briefing; the human submits actions.
                human_actions = await self.show_briefing(
                    self.human_nation,
                    state,
                    history,
                    private_intel[self.human_nation],
                    scenario,
                )

                # Wait for AI agents (usually already done) before resolving.
                await self.show_waiting(
                    f"Turn {turn}: waiting for AI nations…"
                )
                all_actions: dict[NationName, TurnActions] = {
                    self.human_nation: human_actions
                }
                for nation, task in ai_tasks.items():
                    all_actions[nation] = await task

                await self.show_waiting(
                    f"Turn {turn}: facilitator resolving the actions of all three nations…"
                )

                adjusted_state, econ_changes = apply_economic_adjustments(state, scenario)
                engine_state, applied_costs, unmatched = apply_action_costs(
                    adjusted_state, all_actions, scenario,
                )
                prev_state = engine_state.model_copy(deep=True)

                resolution = await resolve_turn(
                    engine_state, all_actions, history, turns_since_event,
                    facilitator, econ_changes, applied_costs, unmatched,
                )
                state, _applied_changes, _change_warnings = apply_changes(
                    engine_state, resolution.changes,
                )

                await self.show_resolution(
                    resolution, self.human_nation, prev_state, state,
                )

                turn_records.append(
                    TurnRecord(
                        turn=turn, actions=all_actions,
                        resolution=resolution, final_state=state,
                    )
                )
                history.append(f"Turn {turn}: {resolution.narrative}")
                for nation in NationName:
                    nation_intel = resolution.private_intel.get(nation, [])
                    if nation_intel:
                        private_intel[nation].extend(nation_intel)
                if resolution.event_injected:
                    turns_since_event = 0
                else:
                    turns_since_event += 1

            await self.show_waiting("Generating final summary…")
            summary = await generate_summary(state, history, summary_agent_inst)
            await self.show_summary(summary)

            game_log = GameLog(
                timestamp=timestamp,
                metadata=RunMetadata(
                    scenario_name=self.scenario_name,
                    scenario_display_name=scenario.meta.name,
                    mode="human",
                    human_nation=self.human_nation,
                    seed=self.seed,
                    models=settings.models.model_dump(),
                    config=settings.model_dump(),
                    retries=settings.retries,
                    default_turns=settings.default_turns,
                    langfuse=settings.langfuse,
                ),
                num_turns=turns,
                initial_state=initial_state,
                turns=turn_records,
                summary=summary,
            )
            self.result = (summary, game_log)
        except BaseException as e:
            self.game_error = e
        finally:
            self.exit()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_game_tui(
    scenario_name: str,
    num_turns: int | None,
    human_nation: NationName,
    seed: int | None = None,
) -> tuple[GameSummary, GameLog]:
    """Run the full human-player game loop inside a single long-lived TUI."""
    app = GameApp(scenario_name, num_turns, human_nation, seed=seed)
    await app.run_async()
    if app.game_error is not None:
        raise app.game_error
    if app.result is None:
        raise RuntimeError("TUI exited before the game completed.")
    return app.result
