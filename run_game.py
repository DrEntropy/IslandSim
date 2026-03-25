import argparse
import asyncio
import os
from pathlib import Path

import dotenv

dotenv.load_dotenv()

if os.environ.get("LANGFUSE_SECRET_KEY"):
    from pydantic_ai import Agent

    Agent.instrument_all()
    print("Langfuse tracing enabled")
else:
    print("Langfuse tracing disabled (no LANGFUSE_SECRET_KEY found)")

from islandsim.game import run_game


def main():
    parser = argparse.ArgumentParser(description="Run an IslandSim tabletop exercise")
    parser.add_argument(
        "turns",
        nargs="?",
        type=int,
        default=4,
        help="Number of turns to run (default: 4)",
    )
    args = parser.parse_args()

    summary, game_log = asyncio.run(run_game(num_turns=args.turns))
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
