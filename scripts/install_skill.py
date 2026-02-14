#!/usr/bin/env python3
"""
Install this skill for Claude, Codex, or Gemini.

Usage:
  python scripts/install_skill.py --platform codex --scope user
  python scripts/install_skill.py --platform claude --scope project --project-root .
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SKILL_NAME = "wan2gp-operator"


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Install wan2gp-operator for a target platform")
    parser.add_argument("--platform", default="codex", choices=["claude", "codex", "gemini"])
    parser.add_argument("--scope", default="user", choices=["user", "project"])
    parser.add_argument("--project-root", help="Required for --scope project")
    return parser.parse_args()


def resolve_destination(platform: str, scope: str, project_root: str | None) -> Path:
    """Resolve destination skill path."""
    if scope == "user":
        home = Path.home()
        roots = {
            "claude": home / ".claude" / "skills",
            "codex": home / ".agents" / "skills",
            "gemini": home / ".gemini" / "skills",
        }
        return roots[platform]

    if not project_root:
        raise ValueError("--project-root is required when --scope project")
    root = Path(project_root).expanduser().resolve()
    roots = {
        "claude": root / ".claude" / "skills",
        "codex": root / ".agents" / "skills",
        "gemini": root / ".gemini" / "skills",
    }
    return roots[platform]


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    try:
        source = Path(__file__).resolve().parent.parent
        if source.name != SKILL_NAME:
            raise RuntimeError(f"Unexpected source folder: {source}")

        destination_root = resolve_destination(args.platform, args.scope, args.project_root)
        destination = destination_root / SKILL_NAME
        destination_root.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        print(
            json.dumps(
                {
                    "status": "success",
                    "platform": args.platform,
                    "scope": args.scope,
                    "destination": str(destination),
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
