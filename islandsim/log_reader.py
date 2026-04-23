"""Render a saved GameLog JSON file into a human-readable transcript."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from islandsim.models import (
    ActionVisibility,
    GameLog,
    NationName,
    Resources,
    TurnRecord,
    WorldState,
)

BAR = "=" * 60
NATION_ORDER = [NationName.NARU, NationName.VELDARA, NationName.TAUMA]
RESOURCE_KEYS = ("military", "treasury", "food", "support")
RESOURCE_LABELS = ("M", "T", "F", "S")


def _resource_row(name: str, res: Resources, prev: Resources | None = None) -> str:
    parts = []
    for key, label in zip(RESOURCE_KEYS, RESOURCE_LABELS):
        cur = getattr(res, key)
        if prev is None:
            parts.append(f"{label}={cur}")
        else:
            delta = cur - getattr(prev, key)
            parts.append(f"{label}={cur} ({delta:+d})")
    return f"    {name.upper():<8} " + " ".join(parts)


def _render_header(log: GameLog, out: list[str]) -> None:
    out.append(BAR)
    out.append(f"  ISLANDSIM GAME LOG — {log.timestamp}")
    out.append(f"  {log.num_turns} turn(s)")
    out.append(BAR)
    out.append("")
    out.append("Opening Resources:")
    for n in NATION_ORDER:
        out.append(_resource_row(n.value, log.initial_state.nations[n].resources))
    out.append("")
    out.append(f"Reef Maru status: {log.initial_state.reef_maru_status}")
    out.append("")


def _render_turn(
    turn: TurnRecord,
    total: int,
    prev_state: WorldState,
    out: list[str],
    verbose: bool,
) -> None:
    out.append(BAR)
    out.append(f"  TURN {turn.turn} of {total}")
    out.append(BAR)
    out.append("")
    out.append("Country agents deliberating...")
    out.append("")

    for nation in NATION_ORDER:
        ta = turn.actions.get(nation)
        if ta is None:
            continue
        out.append(f"  {nation.value.upper()} actions:")
        for i, act in enumerate(ta.actions, 1):
            vis = "PUBLIC" if act.visibility == ActionVisibility.PUBLIC else "SECRET"
            target = f" -> {act.target.value}" if act.target else ""
            out.append(f"    {i}. [{vis}]{target} {act.description}")
        if verbose and ta.reasoning:
            out.append("    reasoning:")
            for line in ta.reasoning.splitlines():
                out.append(f"      {line}")
        out.append("")

    out.append("Facilitator resolving...")
    out.append("")

    if turn.resolution.event_injected:
        out.append(f"  EVENT: {turn.resolution.event_injected}")
        out.append("")

    out.append("  NARRATIVE:")
    for line in turn.resolution.narrative.splitlines():
        out.append(f"    {line}")
    out.append("")

    if verbose and turn.resolution.action_results:
        out.append("  ACTION RESULTS:")
        for r in turn.resolution.action_results:
            out.append(f"    - [{r.nation.value}] {r.action_description}")
            for line in r.outcome.splitlines():
                out.append(f"        {line}")
            for tgt, changes in r.resource_changes.items():
                deltas = ", ".join(f"{k}{v:+d}" for k, v in changes.items())
                out.append(f"        Δ {tgt.value}: {deltas}")
            if r.detected_by:
                detected = ", ".join(n.value for n in r.detected_by)
                out.append(f"        detected by: {detected}")
        out.append("")

    if verbose and turn.resolution.private_intel:
        out.append("  PRIVATE INTEL:")
        for nation, items in turn.resolution.private_intel.items():
            if not items:
                continue
            out.append(f"    {nation.value}:")
            for item in items:
                out.append(f"      - {item}")
        out.append("")

    if turn.resolution.skill_rolls:
        out.append("  SKILL ROLLS:")
        for r in turn.resolution.skill_rolls:
            verdict = "SUCCESS" if r.success else "FAIL"
            out.append(
                f"    - {r.attacker.value} vs {r.defender.value} "
                f"(diff +{r.difficulty}): "
                f"{r.attacker_skill} - {r.defender_skill} "
                f"{r.roll:+d} = {r.margin:+d} → {verdict}"
            )
            out.append(f"        ctx: {r.context}")
        out.append("")

    out.append("  RESOURCES:")
    new_state = turn.resolution.updated_state
    for n in NATION_ORDER:
        out.append(
            _resource_row(
                n.value,
                new_state.nations[n].resources,
                prev_state.nations[n].resources,
            )
        )
    out.append("")


def _render_summary(log: GameLog, out: list[str]) -> None:
    out.append(BAR)
    out.append("  GAME SUMMARY")
    out.append(BAR)
    out.append("")
    for line in log.summary.narrative.splitlines():
        out.append(f"  {line}")
    out.append("")
    out.append("  NATION ASSESSMENTS:")
    for n in NATION_ORDER:
        assessment = log.summary.nation_assessments.get(n)
        if assessment is None:
            continue
        out.append(f"    {n.value.upper()}:")
        for line in assessment.splitlines():
            out.append(f"      {line}")
    out.append("")
    out.append("  REEF MARU OUTCOME:")
    for line in log.summary.reef_maru_outcome.splitlines():
        out.append(f"    {line}")
    out.append("")


def render(log: GameLog, verbose: bool = False) -> str:
    out: list[str] = []
    _render_header(log, out)
    prev = log.initial_state
    for turn in log.turns:
        _render_turn(turn, log.num_turns, prev, out, verbose)
        prev = turn.resolution.updated_state
    _render_summary(log, out)
    return "\n".join(out)


def _pick_log(path: Path | None) -> Path:
    if path is not None:
        return path
    logs_dir = Path("logs")
    candidates = sorted(logs_dir.glob("islandsim_*.json"))
    if not candidates:
        sys.exit(f"No log files found in {logs_dir.resolve()}")
    return candidates[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", type=Path, help="Log file (default: newest in logs/)")
    ap.add_argument("--out", type=Path, help="Write to file instead of stdout")
    ap.add_argument("--verbose", action="store_true", help="Include reasoning, action results, private intel")
    args = ap.parse_args()

    log_path = _pick_log(args.path)
    log = GameLog.model_validate_json(log_path.read_text())
    text = render(log, verbose=args.verbose)

    if args.out:
        args.out.write_text(text)
        print(f"Wrote {args.out} ({len(text)} bytes) from {log_path}", file=sys.stderr)
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
