#!/usr/bin/env python3
"""
Unified Wan2GP Operator entrypoint for Codex workflows.

Usage:
  python scripts/wan2gp_operator.py bootstrap --execute --launch-ui
  python scripts/wan2gp_operator.py assess
  python scripts/wan2gp_operator.py setup --target-dir E:/tools/Wan2GP
  python scripts/wan2gp_operator.py launch-ui --wan-root E:/tools/Wan2GP
  python scripts/wan2gp_operator.py compose --prompt "cinematic city timelapse"
  python scripts/wan2gp_operator.py run --wan-root E:/tools/Wan2GP --process ./job.json --dry-run
  python scripts/wan2gp_operator.py evolve --wan-root E:/tools/Wan2GP
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_MAP = {
    "bootstrap": "bootstrap_wan2gp.py",
    "assess": "assess_install.py",
    "setup": "setup_wan2gp.py",
    "launch-ui": "launch_wan2gp.py",
    "compose": "compose_settings.py",
    "plan": "plan_run.py",
    "run": "run_headless.py",
    "diagnose": "diagnose_failure.py",
    "updates": "check_updates.py",
    "evolve": "evolve_operator.py",
}


def _parse_args() -> tuple[argparse.Namespace, list[str]]:
    """Parse top-level command and pass-through args."""
    parser = argparse.ArgumentParser(description="Wan2GP Operator unified CLI")
    parser.add_argument(
        "command",
        choices=sorted(SCRIPT_MAP.keys()),
        help="Operator function to run",
    )
    parser.add_argument(
        "--script-help",
        action="store_true",
        help="Show help for the selected underlying script",
    )
    return parser.parse_known_args()


def main() -> int:
    """CLI entrypoint."""
    args, remainder = _parse_args()
    script_name = SCRIPT_MAP[args.command]
    script_path = Path(__file__).resolve().parent / script_name

    forward = remainder
    if args.script_help:
        forward = ["--help"]

    command = [sys.executable, str(script_path), *forward]
    process = subprocess.run(command)
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
