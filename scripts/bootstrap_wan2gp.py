#!/usr/bin/env python3
"""
Bootstrap Wan2GP from scratch: assess -> setup plan/execute -> optional UI launch.

Usage:
  python scripts/bootstrap_wan2gp.py
  python scripts/bootstrap_wan2gp.py --execute --launch-ui
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Bootstrap Wan2GP from scratch")
    parser.add_argument("--target-dir", default="./Wan2GP", help="Target Wan2GP root path")
    parser.add_argument("--env-manager", choices=["auto", "conda", "venv", "none"], default="auto")
    parser.add_argument("--env-name", default="wan2gp", help="Conda env name or venv folder name")
    parser.add_argument("--python-version", default="3.11.14", help="Python version for conda env")
    parser.add_argument("--execute", action="store_true", help="Execute setup steps")
    parser.add_argument("--launch-ui", action="store_true", help="Launch Wan2GP UI after successful setup")
    parser.add_argument("--force", action="store_true", help="Proceed even if readiness verdict is not_recommended")
    return parser.parse_args()


def _run_json(script_path: Path, extra_args: list[str]) -> tuple[int, dict[str, Any] | None, str]:
    """Run a script and parse JSON response."""
    command = [sys.executable, str(script_path), *extra_args]
    process = subprocess.run(command, text=True, capture_output=True)
    payload = process.stdout.strip() or process.stderr.strip()
    try:
        parsed = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = None
    return process.returncode, parsed, payload


def main() -> int:
    """CLI entrypoint."""
    here = Path(__file__).resolve().parent
    assess_script = here / "assess_install.py"
    setup_script = here / "setup_wan2gp.py"
    launch_script = here / "launch_wan2gp.py"

    args = _parse_args()
    target = str(Path(args.target_dir).expanduser().resolve())

    rc_assess, assess_report, assess_raw = _run_json(assess_script, [])
    if rc_assess != 0 or not assess_report:
        print(json.dumps({"status": "error", "stage": "assess", "raw": assess_raw}, indent=2), file=sys.stderr)
        return 1

    verdict = assess_report.get("recommendation", {}).get("verdict")
    if verdict == "not_recommended" and not args.force:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "Machine assessed as not_recommended.",
                    "assessment": assess_report,
                    "hint": "Re-run with --force to continue anyway.",
                },
                indent=2,
            )
        )
        return 2

    setup_args = [
        "--target-dir",
        target,
        "--env-manager",
        args.env_manager,
        "--env-name",
        args.env_name,
        "--python-version",
        args.python_version,
    ]
    if args.execute:
        setup_args.append("--execute")
    rc_setup, setup_report, setup_raw = _run_json(setup_script, setup_args)
    if rc_setup != 0 or not setup_report:
        print(
            json.dumps(
                {
                    "status": "error",
                    "stage": "setup",
                    "assessment": assess_report,
                    "raw": setup_raw,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    launch_report: dict[str, Any] | None = None
    if args.execute and args.launch_ui and setup_report.get("status") == "success":
        launch_args = ["--wan-root", target, "--env-manager", args.env_manager, "--env-name", args.env_name]
        rc_launch, launch_report, launch_raw = _run_json(launch_script, launch_args)
        if rc_launch != 0:
            launch_report = {"status": "error", "raw": launch_raw}

    final_report = {
        "status": "success",
        "target_dir": target,
        "assessment": assess_report,
        "setup": setup_report,
        "launch": launch_report,
        "next": (
            "Wan2GP setup executed. Use compose/run commands now."
            if args.execute
            else "Setup plan generated. Re-run with --execute to install."
        ),
    }
    print(json.dumps(final_report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
