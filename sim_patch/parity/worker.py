"""Disposable native replay process; launched from the run's frozen harness."""
import argparse
from pathlib import Path

from .adapter import Comparator, replay_sequence
from .core import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-empty-prefix", action="store_true")
    args = parser.parse_args()
    comparator = Comparator(args.engine, Path(__file__).resolve().parents[2])
    result = replay_sequence(comparator, read_json(args.input), require_actions=not args.allow_empty_prefix)
    write_json(args.output, result)


if __name__ == "__main__":
    main()
