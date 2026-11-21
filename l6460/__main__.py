"""Run with: python -m l6460 serve [--to-file FOLDER] | settings"""
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="l6460")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("serve", help="receive jobs from the L6460 Duplex printer")
    run.add_argument("--to-file", type=Path,
                     help="test mode: save the printer data in this folder and use no paper")
    commands.add_parser("settings", help="choose the paper size for 2-sided printing")
    args = parser.parse_args()

    if args.command == "settings":
        from .ui import run as run_settings
        run_settings()
    else:
        from .service import serve
        serve(args.to_file)


if __name__ == "__main__":
    main()
