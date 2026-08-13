from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .ddcli import DDCLI, DDCLIError
from .utils import default_config_path, load_config
from .workflow import Cancelled, LunchWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="team-lunch",
        description="Create and safely submit a DoorDash group lunch from the terminal.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="JSON configuration file (default: config.json beside the app or in the current folder)",
    )
    parser.add_argument("--dd-cli", dest="dd_cli", help="Path to the dd-cli executable")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("start", help="Create a new group lunch cart")
    subparsers.add_parser("resume", help="Continue the last saved group lunch")
    subparsers.add_parser("doctor", help="Check dd-cli, sign-in, and local configuration")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "start"
    try:
        config_path = args.config.expanduser().resolve()
        config = load_config(config_path)
        workflow = LunchWorkflow(DDCLI(executable=args.dd_cli), config, config_path)
        if command == "start":
            workflow.start()
        elif command == "resume":
            workflow.resume()
        elif command == "doctor":
            workflow.doctor()
        else:
            parser.error(f"Unknown command: {command}")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled. No automatic retry was attempted.")
        return 130
    except Cancelled as exc:
        print(f"\n{exc}")
        return 0
    except (DDCLIError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
