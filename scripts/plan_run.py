#!/usr/bin/env python3
"""
Plan a Wan2GP headless command with validation.

Usage:
  python scripts/plan_run.py --wan-root /path/to/Wan2GP --process queue.zip
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _wan2gp_common import (
    ATTENTION_MODES,
    MODEL_PRESETS,
    build_wan2gp_command,
    command_to_string,
    is_attention_known_unsupported,
    is_flag_known_unsupported,
    load_operator_state,
    resolve_optional_path,
    resolve_python_executable,
    resolve_process_file,
    resolve_wan_root,
    strip_flag_with_value,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Plan a Wan2GP headless command")
    parser.add_argument("--wan-root", required=True, help="Path to Wan2GP root folder")
    parser.add_argument("--process", required=True, help="Queue/settings file (.zip or .json)")
    parser.add_argument("--output-dir", help="Optional output directory override")
    parser.add_argument(
        "--python-exe",
        default="auto",
        help="Python executable to run wgp.py (default: auto-detect Wan2GP venv)",
    )
    parser.add_argument("--attention", choices=sorted(ATTENTION_MODES), help="Attention backend")
    parser.add_argument("--profile", default="4", help="Wan2GP memory profile (e.g. 3, 4, 4.5)")
    parser.add_argument("--verbose", type=int, default=1, choices=[0, 1, 2], help="Verbose level")
    parser.add_argument("--dry-run", action="store_true", help="Validate queue without generating")
    parser.add_argument("--compile", action="store_true", help="Enable --compile")
    parser.add_argument("--fp16", action="store_true", help="Enable --fp16")
    parser.add_argument("--teacache", type=float, help="TeaCache multiplier")
    parser.add_argument(
        "--model-preset",
        default="none",
        choices=sorted(MODEL_PRESETS.keys()),
        help="Model preset switch",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Pass-through extra argument (can be repeated)",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()

    try:
        wan_root = resolve_wan_root(args.wan_root)
        process_file = resolve_process_file(args.process, wan_root)
        output_dir = resolve_optional_path(args.output_dir, wan_root)
        python_exe = resolve_python_executable(args.python_exe, wan_root)
        state = load_operator_state(wan_root)

        command = build_wan2gp_command(
            python_exe=python_exe,
            process_file=process_file,
            output_dir=output_dir,
            attention=args.attention,
            profile=args.profile,
            verbose=args.verbose,
            dry_run=args.dry_run,
            compile_enabled=args.compile,
            fp16=args.fp16,
            teacache=args.teacache,
            model_preset=args.model_preset,
            extra_args=args.extra_arg,
        )
        if args.attention and is_attention_known_unsupported(state, args.attention):
            if "--attention" in command:
                idx = command.index("--attention")
                if idx + 1 < len(command):
                    command[idx + 1] = "sdpa"
        if args.teacache is not None and is_flag_known_unsupported(state, "--teacache"):
            command = strip_flag_with_value(command, "--teacache")

        notes: list[str] = []
        if process_file.suffix.lower() == ".json":
            notes.append(
                "JSON settings files may reference media paths outside Wan2GP. "
                "Ensure referenced files are reachable."
            )
        if args.model_preset == "none":
            notes.append("No model preset switch was added. Wan2GP default model selection will apply.")
        if python_exe == "python" and args.python_exe == "auto":
            notes.append("No local Wan2GP venv python detected; using system python from PATH.")
        if args.teacache is not None and is_flag_known_unsupported(state, "--teacache"):
            notes.append(
                "Learned compatibility state marks --teacache unsupported for this Wan2GP build; "
                "command excludes it."
            )
        if args.attention and is_attention_known_unsupported(state, args.attention):
            notes.append(
                f"Learned compatibility state marks attention '{args.attention}' unsupported; "
                "command uses 'sdpa' fallback."
            )

        report = {
            "status": "success",
            "wan_root": str(wan_root),
            "process_file": str(process_file),
            "output_dir": str(output_dir) if output_dir else None,
            "python_executable": python_exe,
            "command": command,
            "command_string": command_to_string(command),
            "notes": notes,
        }
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
