#!/usr/bin/env python3
"""
Assemble generated clips into a music video using ffmpeg.

Usage:
  python scripts/music_assemble_ffmpeg.py --audio ./song.mp3 --manifest ./generation_manifest.json
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
    parser = argparse.ArgumentParser(description="Assemble music video from generated Wan2GP clips")
    parser.add_argument("--audio", required=True, help="Path to song/audio file")
    parser.add_argument("--manifest", required=True, help="Path to generation manifest JSON")
    parser.add_argument("--output", help="Output rendered MP4 path")
    parser.add_argument("--resolution", default="1280x720", help="Target output resolution WIDTHxHEIGHT")
    parser.add_argument("--fps", type=int, default=24, help="Target output fps")
    parser.add_argument("--max-clips", type=int, help="Optional cap on number of clips")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg executable path")
    parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe executable path")
    parser.add_argument("--crf", type=int, default=18, help="CRF value for x264 encoding")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate files")
    return parser.parse_args()


def _parse_resolution(resolution: str) -> tuple[int, int]:
    cleaned = resolution.lower().replace(" ", "")
    if "x" not in cleaned:
        raise ValueError("Resolution must be WIDTHxHEIGHT")
    width_text, height_text = cleaned.split("x", 1)
    width = int(width_text)
    height = int(height_text)
    if width <= 0 or height <= 0:
        raise ValueError("Resolution dimensions must be positive")
    return width, height


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _probe_duration(path: Path, ffprobe_bin: str) -> float:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    process = _run(command)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip())
    return float(process.stdout.strip())


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return loaded


def _best_take(takes: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for take in takes:
        if str(take.get("status", "")).lower() != "success":
            continue
        video_file = take.get("video_file")
        if not video_file:
            continue
        path = Path(str(video_file)).expanduser().resolve()
        if not path.exists():
            continue
        score = float(take.get("quality_score", 0.0) or 0.0)
        candidates.append((score, take))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _select_clip_paths(manifest: dict[str, Any], max_clips: int | None) -> list[Path]:
    clips: list[Path] = []
    shots = manifest.get("shots", [])
    if isinstance(shots, list):
        for shot in shots:
            takes = shot.get("takes", [])
            if not isinstance(takes, list):
                continue
            best = _best_take(takes)
            if not best:
                continue
            clip = Path(str(best.get("video_file"))).expanduser().resolve()
            clips.append(clip)

    if not clips:
        raw_clips = manifest.get("clips", [])
        if isinstance(raw_clips, list):
            for value in raw_clips:
                clip = Path(str(value)).expanduser().resolve()
                if clip.exists():
                    clips.append(clip)

    if max_clips is not None:
        clips = clips[: max(1, max_clips)]
    return clips


def _resolve_output_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    folder = Path.cwd() / "wan2gp_music_jobs" / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (folder / f"music-video-{ts}.mp4").resolve()


def _normalize_clip(
    ffmpeg_bin: str,
    source: Path,
    destination: Path,
    width: int,
    height: int,
    fps: int,
    crf: int,
) -> None:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={fps},format=yuv420p"
    )
    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source),
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        str(destination),
    ]
    process = _run(command)
    if process.returncode != 0:
        raise RuntimeError(
            f"Failed to normalize clip {source}: {process.stderr.strip() or process.stdout.strip()}"
        )


def _concat_clips(ffmpeg_bin: str, list_file: Path, out_file: Path, crf: int) -> None:
    command = [
        ffmpeg_bin,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        str(out_file),
    ]
    process = _run(command)
    if process.returncode != 0:
        raise RuntimeError(f"Failed to concatenate clips: {process.stderr.strip() or process.stdout.strip()}")


def _mux_audio(
    ffmpeg_bin: str,
    loop_video: Path,
    audio_file: Path,
    output_file: Path,
    crf: int,
) -> None:
    command = [
        ffmpeg_bin,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(loop_video),
        "-i",
        str(audio_file),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_file),
    ]
    process = _run(command)
    if process.returncode != 0:
        raise RuntimeError(f"Failed to mux audio/video: {process.stderr.strip() or process.stdout.strip()}")


def main() -> int:
    temp_dir: Path | None = None
    try:
        args = _parse_args()
        if shutil.which(args.ffmpeg_bin) is None:
            raise FileNotFoundError(f"ffmpeg not found on PATH: {args.ffmpeg_bin}")
        if shutil.which(args.ffprobe_bin) is None:
            raise FileNotFoundError(f"ffprobe not found on PATH: {args.ffprobe_bin}")

        audio_file = Path(args.audio).expanduser().resolve()
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        manifest_file = Path(args.manifest).expanduser().resolve()
        if not manifest_file.exists():
            raise FileNotFoundError(f"Manifest file not found: {manifest_file}")

        manifest = _load_json(manifest_file)
        clip_paths = _select_clip_paths(manifest, args.max_clips)
        if not clip_paths:
            raise ValueError("No successful clips found in manifest.")

        width, height = _parse_resolution(args.resolution)
        output_file = _resolve_output_path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        temp_dir = output_file.parent / f".assemble_tmp_{ts}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        normalized_files: list[Path] = []

        for index, clip in enumerate(clip_paths, start=1):
            normalized = temp_dir / f"clip_{index:03d}.mp4"
            _normalize_clip(
                ffmpeg_bin=args.ffmpeg_bin,
                source=clip,
                destination=normalized,
                width=width,
                height=height,
                fps=args.fps,
                crf=args.crf,
            )
            normalized_files.append(normalized)

        concat_list = temp_dir / "concat_list.txt"
        lines = []
        for clip in normalized_files:
            line = "file '" + clip.as_posix().replace("'", "'\\''") + "'"
            lines.append(line)
        concat_list.write_text("\n".join(lines), encoding="utf-8")

        concat_video = temp_dir / "concat_video.mp4"
        _concat_clips(args.ffmpeg_bin, concat_list, concat_video, args.crf)
        _mux_audio(args.ffmpeg_bin, concat_video, audio_file, output_file, args.crf)

        report_file = output_file.with_suffix(".assembly.json")
        report = {
            "status": "success",
            "manifest_file": str(manifest_file),
            "audio_file": str(audio_file),
            "output_file": str(output_file),
            "report_file": str(report_file),
            "resolution": f"{width}x{height}",
            "fps": args.fps,
            "clips_used": [str(path) for path in clip_paths],
            "normalized_clip_count": len(normalized_files),
            "audio_duration_seconds": round(_probe_duration(audio_file, args.ffprobe_bin), 4),
            "output_duration_seconds": round(_probe_duration(output_file, args.ffprobe_bin), 4),
            "temp_dir": str(temp_dir),
        }
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    finally:
        if temp_dir is not None and temp_dir.exists() and "args" in locals() and not args.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
