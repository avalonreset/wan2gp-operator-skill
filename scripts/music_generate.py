#!/usr/bin/env python3
"""
Generate planned music-video shots via Wan2GP operator scripts.

Usage:
  python scripts/music_generate.py --plan ./music-plan.json --wan-root E:/tools/Wan2GP --execute-generation
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Wan2GP shots from a music-video plan")
    parser.add_argument("--plan", required=True, help="Path to music_video_plan JSON")
    parser.add_argument("--wan-root", help="Path to Wan2GP root (required when --execute-generation)")
    parser.add_argument("--output-root", help="Output root for process files, logs, and renders")
    parser.add_argument("--manifest-out", help="Explicit output path for generation manifest JSON")
    parser.add_argument(
        "--quality-default",
        choices=["draft", "balanced", "quality"],
        default="balanced",
        help="Fallback compose quality when shot does not specify quality_hint",
    )
    parser.add_argument("--max-shots", type=int, help="Optional max number of shots to process")
    parser.add_argument("--max-takes-per-shot", type=int, help="Optional cap on takes per shot")
    parser.add_argument("--execute-generation", action="store_true", help="Run Wan2GP generation")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run into run_headless")
    parser.add_argument("--attention", choices=["sdpa", "flash", "sage", "sage2"], help="Override attention mode")
    parser.add_argument("--profile", help="Override profile mode")
    parser.add_argument("--teacache", type=float, help="Override teacache")
    parser.add_argument("--compile-mode", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--timeout-minutes", type=int, default=0, help="Timeout per run attempt")
    parser.add_argument("--evolve-on-failure", action="store_true", help="Run evolve script for failed takes")
    parser.add_argument("--preview-dir", help="Optional directory to write per-shot preview stills and gifs")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg executable path for preview generation")
    parser.add_argument("--preview-stills", type=int, default=3, help="Number of still preview frames per clip")
    parser.add_argument("--python-exe", default=sys.executable, help="Python executable for script chaining")
    parser.add_argument("--verbose", action="store_true", help="Include verbose command output snippets")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected JSON object in: {path}")
    return loaded


def _resolve_output_root(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    folder = Path.cwd() / "wan2gp_music_jobs" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (folder / f"music-run-{ts}").resolve()


def _run_process(command: list[str]) -> subprocess.CompletedProcess[str]:
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


def _quality_from_shot(shot: dict[str, Any], fallback: str) -> str:
    quality = str(shot.get("quality_hint", fallback)).strip().lower()
    if quality not in {"draft", "balanced", "quality"}:
        return fallback
    return quality


def _short_tail(text: str, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _find_latest_mp4(folder: Path) -> Path | None:
    if not folder.exists():
        return None
    candidates = list(folder.rglob("*.mp4"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _quality_score_from_file(video_file: Path | None) -> float | None:
    if video_file is None:
        return None
    size_mb = video_file.stat().st_size / (1024 * 1024)
    if size_mb <= 0.5:
        return 0.15
    if size_mb <= 2.0:
        return 0.35
    if size_mb <= 6.0:
        return 0.6
    return 0.8


def _run_no_throw(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _build_preview_still_select(frame_count: int, stills: int) -> str:
    still_count = max(1, stills)
    if frame_count <= 1:
        return "eq(n,0)"
    indexes = []
    for idx in range(still_count):
        position = int(round(idx * (frame_count - 1) / max(1, still_count - 1)))
        indexes.append(max(0, min(frame_count - 1, position)))
    indexes = list(dict.fromkeys(indexes))
    return "+".join(f"eq(n\\,{value})" for value in indexes)


def _probe_frame_count(video_file: Path, ffprobe_bin: str) -> int:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_read_frames",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(video_file),
    ]
    result = _run_no_throw(command)
    if result.returncode != 0:
        return 0
    try:
        return int((result.stdout or "0").strip() or "0")
    except Exception:
        return 0


def _generate_previews(
    video_file: Path,
    preview_dir: Path,
    take_id: str,
    ffmpeg_bin: str,
    preview_stills: int,
) -> dict[str, Any]:
    preview_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which(ffmpeg_bin) is None:
        return {"status": "skipped", "reason": f"ffmpeg not found: {ffmpeg_bin}"}

    frame_count = _probe_frame_count(video_file, "ffprobe")
    select_expr = _build_preview_still_select(frame_count, preview_stills)
    still_pattern = preview_dir / f"{take_id}_preview_%02d.png"
    gif_path = preview_dir / f"{take_id}_preview.gif"

    still_cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_file),
        "-vf",
        f"select='{select_expr}'",
        "-vsync",
        "0",
        str(still_pattern),
    ]
    still_proc = _run_no_throw(still_cmd)

    gif_cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(video_file),
        "-vf",
        "fps=8,scale=416:-1:flags=lanczos",
        "-loop",
        "0",
        str(gif_path),
    ]
    gif_proc = _run_no_throw(gif_cmd)

    stills = sorted(preview_dir.glob(f"{take_id}_preview_*.png"))
    return {
        "status": "success" if still_proc.returncode == 0 and gif_proc.returncode == 0 else "partial",
        "still_paths": [str(path.resolve()) for path in stills],
        "gif_path": str(gif_path.resolve()) if gif_path.exists() else None,
        "still_exit_code": still_proc.returncode,
        "gif_exit_code": gif_proc.returncode,
    }


def _compose_command(
    args: argparse.Namespace,
    shot: dict[str, Any],
    process_file: Path,
    plan_resolution: str,
) -> list[str]:
    duration_seconds = float(shot.get("duration_sec", 3.0) or 3.0)
    quality = _quality_from_shot(shot, args.quality_default)
    command = [
        args.python_exe,
        str(Path(__file__).resolve().parent / "compose_settings.py"),
        "--prompt",
        str(shot.get("prompt", "")).strip(),
        "--negative-prompt",
        str(shot.get("negative_prompt", "")).strip(),
        "--quality",
        quality,
        "--duration-seconds",
        str(duration_seconds),
        "--resolution",
        plan_resolution,
        "--output",
        str(process_file),
    ]
    return command


def _compile_enabled(compose_flags: dict[str, Any], compile_mode: str) -> bool:
    if compile_mode == "on":
        return True
    if compile_mode == "off":
        return False
    return bool(compose_flags.get("compile", False))


def _build_run_command(
    args: argparse.Namespace,
    wan_root: Path,
    process_file: Path,
    shot_output_dir: Path,
    log_file: Path,
    compose_flags: dict[str, Any],
) -> list[str]:
    attention = args.attention or str(compose_flags.get("attention", "sdpa"))
    profile = args.profile or str(compose_flags.get("profile", "4"))
    teacache: float | None
    if args.teacache is not None:
        teacache = args.teacache
    else:
        raw_teacache = compose_flags.get("teacache")
        teacache = float(raw_teacache) if raw_teacache is not None else None

    command = [
        args.python_exe,
        str(Path(__file__).resolve().parent / "run_headless.py"),
        "--wan-root",
        str(wan_root),
        "--process",
        str(process_file),
        "--output-dir",
        str(shot_output_dir),
        "--log-file",
        str(log_file),
        "--attention",
        attention,
        "--profile",
        profile,
    ]
    if teacache is not None:
        command.extend(["--teacache", str(teacache)])
    if _compile_enabled(compose_flags, args.compile_mode):
        command.append("--compile")
    if args.dry_run:
        command.append("--dry-run")
    if args.timeout_minutes > 0:
        command.extend(["--timeout-minutes", str(args.timeout_minutes)])
    return command


def _build_evolve_command(
    args: argparse.Namespace,
    wan_root: Path,
    process_file: Path,
    log_file: Path,
    suggested_file: Path,
) -> list[str]:
    return [
        args.python_exe,
        str(Path(__file__).resolve().parent / "evolve_operator.py"),
        "--wan-root",
        str(wan_root),
        "--log-file",
        str(log_file),
        "--quality-feedback",
        "bad",
        "--process-file",
        str(process_file),
        "--write-suggested-settings",
        str(suggested_file),
    ]


def _takes_for_shot(shot: dict[str, Any], max_takes_per_shot: int | None) -> int:
    planned = int(shot.get("takes", 1) or 1)
    planned = max(1, planned)
    if max_takes_per_shot is not None:
        return min(planned, max(1, max_takes_per_shot))
    return planned


def main() -> int:
    try:
        args = _parse_args()
        plan_file = Path(args.plan).expanduser().resolve()
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan file not found: {plan_file}")
        plan = _load_json(plan_file)
        shots = plan.get("shots", [])
        if not isinstance(shots, list) or not shots:
            raise ValueError("Plan file has no shots to generate.")
        if args.max_shots is not None:
            shots = shots[: max(1, args.max_shots)]

        if args.execute_generation and not args.wan_root:
            raise ValueError("--wan-root is required with --execute-generation")

        wan_root: Path | None = None
        if args.wan_root:
            wan_root = Path(args.wan_root).expanduser().resolve()
            if not wan_root.exists():
                raise FileNotFoundError(f"Wan2GP root not found: {wan_root}")
            if args.execute_generation and not (wan_root / "wgp.py").exists():
                raise FileNotFoundError(f"wgp.py not found in wan root: {wan_root}")

        output_root = _resolve_output_root(args.output_root)
        process_dir = output_root / "process"
        run_dir = output_root / "runs"
        evolve_dir = output_root / "evolve"
        preview_dir = (
            Path(args.preview_dir).expanduser().resolve()
            if args.preview_dir
            else (output_root / "previews").resolve()
        )
        process_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        evolve_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = (
            Path(args.manifest_out).expanduser().resolve()
            if args.manifest_out
            else (output_root / "generation_manifest.json").resolve()
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        plan_resolution = str(plan.get("resolution", "832x480")).strip()
        shot_reports: list[dict[str, Any]] = []
        total_takes = 0
        successful_takes = 0
        failed_takes = 0

        for shot in shots:
            shot_id = str(shot.get("id", f"shot_{len(shot_reports) + 1:03d}"))
            takes = _takes_for_shot(shot, args.max_takes_per_shot)
            shot_report: dict[str, Any] = {
                "shot_id": shot_id,
                "start_sec": shot.get("start_sec"),
                "end_sec": shot.get("end_sec"),
                "duration_sec": shot.get("duration_sec"),
                "priority": shot.get("priority"),
                "prompt": shot.get("prompt"),
                "takes": [],
            }

            for take_index in range(1, takes + 1):
                total_takes += 1
                process_file = process_dir / f"{shot_id}_take{take_index:02d}.json"
                compose_command = _compose_command(args, shot, process_file, plan_resolution)
                compose_proc = _run_process(compose_command)
                compose_text = compose_proc.stdout.strip() or compose_proc.stderr.strip()
                compose_report = _parse_last_json_object(compose_text) or {}

                take_report: dict[str, Any] = {
                    "take_id": f"{shot_id}_take{take_index:02d}",
                    "quality_hint": _quality_from_shot(shot, args.quality_default),
                    "process_file": str(process_file),
                    "compose_command": compose_command,
                    "compose_exit_code": compose_proc.returncode,
                    "compose_report": compose_report,
                    "status": "planned",
                }
                if args.verbose:
                    take_report["compose_output_tail"] = _short_tail(compose_text)

                if compose_proc.returncode != 0 or not process_file.exists():
                    take_report["status"] = "error"
                    take_report["error"] = "compose_failed"
                    failed_takes += 1
                    shot_report["takes"].append(take_report)
                    if args.execute_generation and args.verbose:
                        print(
                            json.dumps(
                                {
                                    "status": "compose_failed",
                                    "shot_id": shot_id,
                                    "take": take_index,
                                }
                            )
                        )
                    if args.execute_generation and args.verbose:
                        continue
                    continue

                if args.execute_generation:
                    assert wan_root is not None
                    shot_take_dir = run_dir / shot_id / f"take_{take_index:02d}"
                    shot_take_dir.mkdir(parents=True, exist_ok=True)
                    log_file = shot_take_dir / "run.log"
                    compose_flags = compose_report.get("recommended_runtime_flags", {})
                    if not isinstance(compose_flags, dict):
                        compose_flags = {}
                    run_command = _build_run_command(
                        args=args,
                        wan_root=wan_root,
                        process_file=process_file,
                        shot_output_dir=shot_take_dir,
                        log_file=log_file,
                        compose_flags=compose_flags,
                    )
                    run_proc = _run_process(run_command)
                    run_text = (run_proc.stdout or "") + ("\n" + run_proc.stderr if run_proc.stderr else "")
                    run_report = _parse_last_json_object(run_text) or {}
                    run_status = str(run_report.get("status", "error" if run_proc.returncode else "success"))
                    take_report.update(
                        {
                            "run_command": run_command,
                            "run_exit_code": run_proc.returncode,
                            "run_report": run_report,
                            "log_file": str(log_file),
                            "status": run_status,
                        }
                    )
                    if args.verbose:
                        take_report["run_output_tail"] = _short_tail(run_text)

                    if run_status == "success" and not args.dry_run:
                        video_file = _find_latest_mp4(shot_take_dir)
                        take_report["video_file"] = str(video_file) if video_file else None
                        take_report["quality_score"] = _quality_score_from_file(video_file)
                        if video_file is not None:
                            take_report["preview"] = _generate_previews(
                                video_file=video_file,
                                preview_dir=preview_dir,
                                take_id=str(take_report["take_id"]),
                                ffmpeg_bin=args.ffmpeg_bin,
                                preview_stills=args.preview_stills,
                            )
                        successful_takes += 1
                    elif run_status == "success" and args.dry_run:
                        successful_takes += 1
                    else:
                        failed_takes += 1
                        if args.evolve_on_failure:
                            suggested = evolve_dir / f"{shot_id}_take{take_index:02d}_suggested.json"
                            evolve_command = _build_evolve_command(
                                args=args,
                                wan_root=wan_root,
                                process_file=process_file,
                                log_file=log_file,
                                suggested_file=suggested,
                            )
                            evolve_proc = _run_process(evolve_command)
                            evolve_text = (evolve_proc.stdout or "") + (
                                "\n" + evolve_proc.stderr if evolve_proc.stderr else ""
                            )
                            evolve_report = _parse_last_json_object(evolve_text) or {}
                            take_report["evolve_command"] = evolve_command
                            take_report["evolve_exit_code"] = evolve_proc.returncode
                            take_report["evolve_report"] = evolve_report
                            if args.verbose:
                                take_report["evolve_output_tail"] = _short_tail(evolve_text)
                shot_report["takes"].append(take_report)

            shot_reports.append(shot_report)

        status = "success"
        if args.execute_generation and successful_takes == 0 and total_takes > 0:
            status = "error"

        manifest = {
            "status": status,
            "plan_file": str(plan_file),
            "manifest_file": str(manifest_path),
            "wan_root": str(wan_root) if wan_root else None,
            "execute_generation": args.execute_generation,
            "dry_run": args.dry_run,
            "output_root": str(output_root),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "shots": shot_reports,
            "summary": {
                "total_shots": len(shot_reports),
                "total_takes": total_takes,
                "successful_takes": successful_takes,
                "failed_takes": failed_takes,
            },
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest, indent=2))
        return 0 if status == "success" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
