import argparse
import asyncio
import os

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

    summary = asyncio.run(run_game(num_turns=args.turns))
    print("\n" + summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
