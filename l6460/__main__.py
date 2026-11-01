"""Run with: python -m l6460 serve [--to-file FOLDER]"""
import argparse
from pathlib import Path

from .service import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="l6460")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("serve", help="receive jobs from the L6460 Duplex printer")
    run.add_argument("--to-file", type=Path,
                     help="test mode: save the printer data in this folder and use no paper")
    args = parser.parse_args()
    serve(args.to_file)


if __name__ == "__main__":
    main()
