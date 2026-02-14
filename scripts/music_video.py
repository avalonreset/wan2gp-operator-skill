#!/usr/bin/env python3
"""
One-command music-video pipeline orchestrator.

Usage:
  python scripts/music_video.py --audio ./song.mp3 --theme "neon summer night" --wan-root E:/tools/Wan2GP --execute-generation
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full Wan2GP music-video pipeline")
    parser.add_argument("--audio", required=True, help="Path to input audio track")
    parser.add_argument("--theme", required=True, help="Visual creative direction")
    parser.add_argument("--brand", default="", help="Optional brand context")
    parser.add_argument("--wan-root", help="Wan2GP root (required with --execute-generation)")
    parser.add_argument("--work-dir", help="Working directory for generated pipeline artifacts")
    parser.add_argument(
        "--style-preset",
        choices=["cinematic", "performance", "abstract", "brand-promo"],
        default="cinematic",
    )
    parser.add_argument("--quality-default", choices=["draft", "balanced", "quality"], default="balanced")
    parser.add_argument("--resolution-plan", default="832x480", help="Resolution for generated Wan2GP shots")
    parser.add_argument("--resolution-final", default="1280x720", help="Final assembled output resolution")
    parser.add_argument("--fps-plan", type=int, default=16, help="FPS for Wan2GP generation plan")
    parser.add_argument("--fps-final", type=int, default=24, help="FPS for final assembled export")
    parser.add_argument("--max-shots", type=int, help="Optional cap on planned shots")
    parser.add_argument("--max-takes-per-shot", type=int, help="Optional cap on takes per shot")
    parser.add_argument("--execute-generation", action="store_true", help="Generate clips via Wan2GP")
    parser.add_argument("--dry-run-generation", action="store_true", help="Run generation in dry-run mode")
    parser.add_argument("--evolve-on-failure", action="store_true", help="Run evolve stage after failed takes")
    parser.add_argument("--timeout-minutes", type=int, default=0, help="Timeout per generated take")
    parser.add_argument("--skip-assemble", action="store_true", help="Skip final ffmpeg assembly")
    parser.add_argument("--python-exe", default=sys.executable, help="Python executable for script chaining")
    parser.add_argument("--verbose", action="store_true", help="Include command output tails in stage reports")
    return parser.parse_args()


def _resolve_work_dir(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    folder = Path.cwd() / "wan2gp_music_jobs" / "pipeline_runs"
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (folder / f"music-video-{ts}").resolve()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _parse_last_json_object(text: str) -> dict[str, Any] | None:
    indices = [idx for idx, char in enumerate(text) if char == "{"]
    for idx in reversed(indices):
        candidate = text[idx:].strip()
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _tail(text: str, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _stage_result(
    name: str,
    command: list[str],
    process: subprocess.CompletedProcess[str],
    verbose: bool,
) -> dict[str, Any]:
    merged = (process.stdout or "") + ("\n" + process.stderr if process.stderr else "")
    parsed = _parse_last_json_object(merged)
    result: dict[str, Any] = {
        "stage": name,
        "command": command,
        "exit_code": process.returncode,
        "report": parsed,
        "status": "success" if process.returncode == 0 else "error",
    }
    if verbose:
        result["output_tail"] = _tail(merged)
    return result


def main() -> int:
    try:
        args = _parse_args()
        audio_file = Path(args.audio).expanduser().resolve()
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        if args.execute_generation and not args.wan_root:
            raise ValueError("--wan-root is required with --execute-generation")

        work_dir = _resolve_work_dir(args.work_dir)
        analysis_dir = work_dir / "analysis"
        plan_dir = work_dir / "plan"
        generate_dir = work_dir / "generate"
        export_dir = work_dir / "export"
        for folder in (analysis_dir, plan_dir, generate_dir, export_dir):
            folder.mkdir(parents=True, exist_ok=True)

        analysis_file = analysis_dir / "audio_analysis.json"
        plan_file = plan_dir / "music_video_plan.json"
        manifest_file = generate_dir / "generation_manifest.json"
        export_file = export_dir / "music_video_master.mp4"
        pipeline_report_file = work_dir / "pipeline_report.json"

        script_dir = Path(__file__).resolve().parent
        stage_reports: list[dict[str, Any]] = []

        analyze_command = [
            args.python_exe,
            str(script_dir / "music_analyze.py"),
            "--audio",
            str(audio_file),
            "--output",
            str(analysis_file),
        ]
        analyze_process = _run(analyze_command)
        analyze_stage = _stage_result("analyze", analyze_command, analyze_process, args.verbose)
        stage_reports.append(analyze_stage)
        if analyze_process.returncode != 0:
            final = {
                "status": "error",
                "error": "audio_analyze_failed",
                "work_dir": str(work_dir),
                "stages": stage_reports,
            }
            pipeline_report_file.write_text(json.dumps(final, indent=2), encoding="utf-8")
            print(json.dumps(final, indent=2))
            return 1

        plan_command = [
            args.python_exe,
            str(script_dir / "music_plan.py"),
            "--analysis",
            str(analysis_file),
            "--theme",
            args.theme,
            "--brand",
            args.brand,
            "--style-preset",
            args.style_preset,
            "--resolution",
            args.resolution_plan,
            "--fps",
            str(args.fps_plan),
            "--output",
            str(plan_file),
        ]
        plan_process = _run(plan_command)
        plan_stage = _stage_result("plan", plan_command, plan_process, args.verbose)
        stage_reports.append(plan_stage)
        if plan_process.returncode != 0:
            final = {
                "status": "error",
                "error": "music_plan_failed",
                "work_dir": str(work_dir),
                "stages": stage_reports,
            }
            pipeline_report_file.write_text(json.dumps(final, indent=2), encoding="utf-8")
            print(json.dumps(final, indent=2))
            return 1

        generate_command = [
            args.python_exe,
            str(script_dir / "music_generate.py"),
            "--plan",
            str(plan_file),
            "--output-root",
            str(generate_dir),
            "--manifest-out",
            str(manifest_file),
            "--quality-default",
            args.quality_default,
        ]
        if args.max_shots is not None:
            generate_command.extend(["--max-shots", str(args.max_shots)])
        if args.max_takes_per_shot is not None:
            generate_command.extend(["--max-takes-per-shot", str(args.max_takes_per_shot)])
        if args.execute_generation:
            generate_command.extend(["--execute-generation", "--wan-root", str(Path(args.wan_root).resolve())])
            if args.dry_run_generation:
                generate_command.append("--dry-run")
            if args.evolve_on_failure:
                generate_command.append("--evolve-on-failure")
            if args.timeout_minutes > 0:
                generate_command.extend(["--timeout-minutes", str(args.timeout_minutes)])
        if args.verbose:
            generate_command.append("--verbose")

        generate_process = _run(generate_command)
        generate_stage = _stage_result("generate", generate_command, generate_process, args.verbose)
        stage_reports.append(generate_stage)
        if generate_process.returncode != 0:
            final = {
                "status": "error",
                "error": "music_generate_failed",
                "work_dir": str(work_dir),
                "stages": stage_reports,
            }
            pipeline_report_file.write_text(json.dumps(final, indent=2), encoding="utf-8")
            print(json.dumps(final, indent=2))
            return 1

        assemble_skipped_reason: str | None = None
        if args.skip_assemble:
            assemble_skipped_reason = "skip_assemble_flag"
        elif not args.execute_generation:
            assemble_skipped_reason = "generation_not_executed"

        if assemble_skipped_reason is None:
            assemble_command = [
                args.python_exe,
                str(script_dir / "music_assemble_ffmpeg.py"),
                "--audio",
                str(audio_file),
                "--manifest",
                str(manifest_file),
                "--output",
                str(export_file),
                "--resolution",
                args.resolution_final,
                "--fps",
                str(args.fps_final),
            ]
            assemble_process = _run(assemble_command)
            assemble_stage = _stage_result("assemble", assemble_command, assemble_process, args.verbose)
            stage_reports.append(assemble_stage)
            if assemble_process.returncode != 0:
                final = {
                    "status": "error",
                    "error": "music_assemble_failed",
                    "work_dir": str(work_dir),
                    "stages": stage_reports,
                }
                pipeline_report_file.write_text(json.dumps(final, indent=2), encoding="utf-8")
                print(json.dumps(final, indent=2))
                return 1
        else:
            stage_reports.append(
                {
                    "stage": "assemble",
                    "status": "skipped",
                    "reason": assemble_skipped_reason,
                }
            )

        final = {
            "status": "success",
            "work_dir": str(work_dir),
            "audio_file": str(audio_file),
            "analysis_file": str(analysis_file),
            "plan_file": str(plan_file),
            "manifest_file": str(manifest_file),
            "output_file": str(export_file) if export_file.exists() else None,
            "stages": stage_reports,
        }
        pipeline_report_file.write_text(json.dumps(final, indent=2), encoding="utf-8")
        print(json.dumps(final, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
