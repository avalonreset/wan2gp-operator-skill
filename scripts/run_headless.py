#!/usr/bin/env python3
"""
Run Wan2GP headless queue/settings processing with structured output.

Usage:
  python scripts/run_headless.py --wan-root /path/to/Wan2GP --process queue.zip
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from _wan2gp_common import (
    ATTENTION_MODES,
    MODEL_PRESETS,
    append_incident,
    build_wan2gp_command,
    command_to_string,
    is_attention_known_unsupported,
    is_flag_known_unsupported,
    load_operator_state,
    mark_unsupported_arg,
    mark_unsupported_attention,
    operator_state_path,
    resolve_optional_path,
    resolve_python_executable,
    resolve_process_file,
    resolve_wan_root,
    save_operator_state,
    strip_flag_with_value,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Run Wan2GP in headless mode")
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
    parser.add_argument("--timeout-minutes", type=int, default=0, help="Kill job after N minutes (0 = no timeout)")
    parser.add_argument("--log-file", help="Optional log file path")
    return parser.parse_args()


def extract_queue_summary(log_text: str) -> dict[str, int | None]:
    """Extract queue completion counts if available."""
    match = re.search(r"Queue completed:\s*(\d+)/(\d+)\s*tasks", log_text, flags=re.IGNORECASE)
    if not match:
        return {"completed": None, "total": None}
    return {"completed": int(match.group(1)), "total": int(match.group(2))}


def _prompt_mentions_text_rendering(prompt: str) -> bool:
    """Detect prompt patterns that commonly degrade base t2v outputs."""
    lowered = prompt.lower()
    risky_terms = ("logo", "text", "typography", "website", "url", ".com", ".pro", "domain")
    return any(term in lowered for term in risky_terms)


def _safe_int(value: object, fallback: int) -> int:
    """Convert value to int with fallback."""
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return fallback


def _build_quality_recommendations(process_file: Path, log_text: str) -> list[str]:
    """Heuristic quality recommendations for the next run."""
    recs: list[str] = []
    settings: dict = {}
    try:
        loaded = json.loads(process_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            settings = loaded
    except Exception:
        return recs

    model_type = str(settings.get("model_type", "")).strip()
    if model_type == "t2v_2_2":
        flow_shift = _safe_int(settings.get("flow_shift"), 12)
        if flow_shift > 6:
            recs.append("For t2v_2_2, lower flow_shift to around 5 to reduce abstract blob artifacts.")
        guidance_phases = _safe_int(settings.get("guidance_phases"), 1)
        if guidance_phases >= 2 and "switch_threshold" not in settings:
            recs.append(
                "t2v_2_2 with multi-phase guidance should set switch_threshold (for example 875) "
                "or generation may remain in high-noise phase too long."
            )

    resolution = str(settings.get("resolution", "")).strip()
    match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", resolution)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        if width * height > 832 * 480:
            recs.append("Use 832x480 while tuning prompts/settings; scale up only after stable composition.")

    prompt = str(settings.get("prompt", "")).strip()
    if _prompt_mentions_text_rendering(prompt):
        recs.append(
            "Prompt requests readable text/logo/domain content; use clean visual prompts for t2v, "
            "then add text in post or switch to i2v pipeline."
        )

    frames = _safe_int(settings.get("video_length"), 49)
    if frames > 81:
        recs.append("Reduce video_length to 33-49 while tuning quality to speed up iteration.")

    if "Queue completed: 0/" in log_text:
        recs.append("Run failed before completion; execute diagnose and evolve before retry.")
    return recs


def _run_once(command: list[str], wan_root: Path, timeout_seconds: int | None) -> tuple[int, float, str, bool]:
    """Run one headless attempt and return exit code, elapsed seconds, logs, timeout flag."""
    start = time.monotonic()
    lines: list[str] = []
    timed_out = False

    process = subprocess.Popen(
        command,
        cwd=wan_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        lines.append(line)
        if timeout_seconds and (time.monotonic() - start) > timeout_seconds:
            timed_out = True
            process.kill()
            break

    exit_code = process.wait()
    elapsed_seconds = round(time.monotonic() - start, 2)
    return exit_code, elapsed_seconds, "".join(lines), timed_out


def _next_retry_command(command: list[str], log_text: str) -> tuple[list[str] | None, str | None, str | None]:
    """Return an auto-adjusted retry command for known incompatibility signatures."""
    if "--teacache" in command and "unrecognized arguments: --teacache" in log_text:
        retried = strip_flag_with_value(command, "--teacache")
        if retried != command:
            return (
                retried,
                "Removed unsupported --teacache flag and retried automatically.",
                "--teacache",
            )
    return None, None, None


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()

    try:
        wan_root = resolve_wan_root(args.wan_root)
        process_file = resolve_process_file(args.process, wan_root)
        output_dir = resolve_optional_path(args.output_dir, wan_root)
        log_file = resolve_optional_path(args.log_file, wan_root)
        python_exe = resolve_python_executable(args.python_exe, wan_root)
        state = load_operator_state(wan_root)
        state_file = operator_state_path(wan_root)
        state_changed = False

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
        auto_adjustments: list[str] = []
        if args.teacache is not None and is_flag_known_unsupported(state, "--teacache"):
            adjusted = strip_flag_with_value(command, "--teacache")
            if adjusted != command:
                command = adjusted
                auto_adjustments.append(
                    "Skipped --teacache based on learned incompatibility state."
                )
        if args.attention and is_attention_known_unsupported(state, args.attention):
            # Keep explicit user choice in logs but force stable fallback.
            fallback_attention = "sdpa"
            if args.attention != fallback_attention and "--attention" in command:
                idx = command.index("--attention")
                if idx + 1 < len(command):
                    command[idx + 1] = fallback_attention
                    auto_adjustments.append(
                        f"Replaced unsupported attention '{args.attention}' with '{fallback_attention}' "
                        "based on learned compatibility state."
                    )

        print(
            json.dumps(
                {
                    "status": "starting",
                    "python_executable": python_exe,
                    "command_string": command_to_string(command),
                    "wan_root": str(wan_root),
                    "process_file": str(process_file),
                    "log_file": str(log_file) if log_file else None,
                    "state_file": str(state_file),
                    "auto_adjustments": auto_adjustments,
                },
                indent=2,
            )
        )

        timeout_seconds = args.timeout_minutes * 60 if args.timeout_minutes > 0 else None
        attempts: list[dict[str, str | int | float | bool]] = []
        combined_logs: list[str] = []
        current_command = command
        exit_code = 1
        elapsed_seconds = 0.0
        timed_out = False

        max_attempts = 2
        for attempt_no in range(1, max_attempts + 1):
            attempt_cmd = command_to_string(current_command)
            if attempt_no > 1:
                print(
                    json.dumps(
                        {"status": "retrying", "attempt": attempt_no, "command_string": attempt_cmd},
                        indent=2,
                    )
                )

            exit_code, elapsed_seconds, attempt_log, timed_out = _run_once(
                current_command, wan_root, timeout_seconds
            )
            attempts.append(
                {
                    "attempt": attempt_no,
                    "command_string": attempt_cmd,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "elapsed_seconds": elapsed_seconds,
                }
            )
            combined_logs.append(f"=== attempt {attempt_no} ===\n{attempt_log}")

            if exit_code == 0 or timed_out:
                break

            retry_command, retry_note, learned_flag = _next_retry_command(current_command, attempt_log)
            if retry_command is None:
                break

            if retry_note:
                auto_adjustments.append(retry_note)
            if learned_flag:
                mark_unsupported_arg(state, learned_flag, evidence=retry_note or "")
                append_incident(
                    state,
                    "unsupported_cli_argument",
                    {
                        "flag": learned_flag,
                        "attempt": attempt_no,
                        "command_string": attempt_cmd,
                    },
                )
                state_changed = True
            current_command = retry_command

        combined_log = "\n\n".join(combined_logs)

        # Learn non-fatal compatibility signals from logs.
        if args.attention and f"attention mode '{args.attention}'. However it is not installed or supported" in combined_log:
            mark_unsupported_attention(
                state,
                args.attention,
                evidence=f"Mode '{args.attention}' reported unsupported in Wan2GP logs.",
            )
            append_incident(
                state,
                "unsupported_attention_mode",
                {"mode": args.attention, "fallback": "sdpa"},
            )
            state_changed = True

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(combined_log, encoding="utf-8")
        if state_changed:
            save_operator_state(wan_root, state)

        queue_summary = extract_queue_summary(combined_log)
        quality_recommendations = _build_quality_recommendations(process_file, combined_log)
        if quality_recommendations:
            append_incident(
                state,
                "quality_recommendations_generated",
                {
                    "process_file": str(process_file),
                    "recommendations": quality_recommendations,
                },
            )
            state_changed = True
            save_operator_state(wan_root, state)
        status = "success" if exit_code == 0 and not timed_out else "error"
        if timed_out:
            status = "timeout"

        report = {
            "status": status,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed_seconds,
            "queue_summary": queue_summary,
            "log_file": str(log_file) if log_file else None,
            "attempts": attempts,
            "auto_adjustments": auto_adjustments,
            "quality_recommendations": quality_recommendations,
            "state_file": str(state_file),
            "next_step": (
                None
                if status == "success"
                else "Run: python scripts/diagnose_failure.py --log-file <log-file>"
            ),
        }
        print(json.dumps(report, indent=2))

        if status == "success":
            return 0
        if status == "timeout":
            return 124
        return 1
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
