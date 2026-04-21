import argparse
import asyncio
import os
from pathlib import Path

import dotenv

dotenv.load_dotenv()

from islandsim.settings import load_settings

_settings = load_settings()

if _settings.langfuse and os.environ.get("LANGFUSE_SECRET_KEY"):
    from pydantic_ai import Agent

    Agent.instrument_all()
    print("Langfuse tracing enabled")
else:
    if not _settings.langfuse:
        print("Langfuse tracing disabled (langfuse: false in config.yaml)")
    else:
        print("Langfuse tracing disabled (no LANGFUSE_SECRET_KEY found)")

from islandsim.game import run_game
from islandsim.models import NationName


def main():
    parser = argparse.ArgumentParser(description="Run an IslandSim tabletop exercise")
    parser.add_argument(
        "turns",
        nargs="?",
        type=int,
        default=None,
        help="Number of turns to run (default: from config.yaml, or 4)",
    )
    parser.add_argument(
        "--scenario",
        default="reef_maru",
        help="Scenario name — loads scenarios/<name>.yaml (default: reef_maru)",
    )
    parser.add_argument(
        "--play",
        type=str,
        default=None,
        choices=["naru", "veldara", "tauma"],
        metavar="NATION",
        help="Play as the specified nation in the TUI (other two remain AI-driven)",
    )
    args = parser.parse_args()

    human_nation = NationName(args.play) if args.play else None
    summary, game_log = asyncio.run(
        run_game(
            scenario_name=args.scenario,
            num_turns=args.turns,
            human_nation=human_nation,
        )
    )
    print("\n" + summary.model_dump_json(indent=2))

    # Save structured game log
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    safe_ts = game_log.timestamp.replace(":", "").replace("-", "").split(".")[0]
    log_path = logs_dir / f"islandsim_{safe_ts}.json"
    log_path.write_text(game_log.model_dump_json(indent=2))
    print(f"\nGame log saved to {log_path}")


if __name__ == "__main__":
    main()
