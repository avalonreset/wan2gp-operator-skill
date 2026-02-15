#!/usr/bin/env python3
"""
Build a shot plan from audio analysis for Wan2GP music videos.

Usage:
  python scripts/music_plan.py --analysis ./audio-analysis.json --theme "neon city dream"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan beat-aligned music-video shots")
    parser.add_argument("--analysis", required=True, help="Path to audio analysis JSON")
    parser.add_argument("--theme", required=True, help="Visual theme for the music video")
    parser.add_argument("--brand", default="", help="Optional brand or product context")
    parser.add_argument(
        "--style-preset",
        choices=["cinematic", "performance", "abstract", "brand-promo"],
        default="cinematic",
        help="High-level style preset",
    )
    parser.add_argument("--resolution", default="832x480", help="Generation resolution for Wan2GP clips")
    parser.add_argument("--fps", type=int, default=16, help="Generation fps for clip planning")
    parser.add_argument("--min-shot-seconds", type=float, default=2.0, help="Minimum shot duration")
    parser.add_argument("--max-shot-seconds", type=float, default=4.0, help="Maximum shot duration")
    parser.add_argument("--takes-hero", type=int, default=3, help="Number of takes for hero shots")
    parser.add_argument("--takes-standard", type=int, default=2, help="Number of takes for standard shots")
    parser.add_argument("--takes-filler", type=int, default=1, help="Number of takes for filler shots")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    parser.add_argument("--output", help="Output plan JSON path")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected JSON object in: {path}")
    return loaded


def _resolve_output_path(path_arg: str | None) -> Path:
    if path_arg:
        return Path(path_arg).expanduser().resolve()
    folder = Path.cwd() / "wan2gp_music_jobs" / "plans"
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return (folder / f"music-plan-{ts}.json").resolve()


def _beat_interval(beats: list[float], fallback_bpm: float) -> float:
    if len(beats) >= 2:
        intervals = [beats[idx + 1] - beats[idx] for idx in range(len(beats) - 1)]
        intervals = [value for value in intervals if value > 0]
        if intervals:
            return float(median(intervals))
    bpm = max(40.0, min(220.0, float(fallback_bpm or 120.0)))
    return 60.0 / bpm


def _snap_forward(target: float, beats: list[float]) -> float:
    if not beats:
        return target
    for beat in beats:
        if beat >= target:
            return beat
    return beats[-1]


def _find_section_at(time_sec: float, sections: list[dict[str, Any]]) -> dict[str, Any]:
    for section in sections:
        start = float(section.get("start_sec", 0.0) or 0.0)
        end = float(section.get("end_sec", 0.0) or 0.0)
        if start <= time_sec < end:
            return section
    if sections:
        return sections[-1]
    return {"label": "section", "energy": "medium", "start_sec": 0.0, "end_sec": time_sec + 1.0}


def _shot_type(section_label: str, energy: str, shot_index: int) -> str:
    label = section_label.lower()
    normalized_energy = energy.lower()
    if shot_index == 1:
        return "hero"
    if "chorus" in label or "drop" in label:
        return "hero"
    if normalized_energy == "low":
        return "filler"
    return "standard"


def _style_tokens(style_preset: str) -> list[str]:
    mapping = {
        "cinematic": [
            "cinematic composition",
            "natural skin tones",
            "high dynamic range lighting",
            "coherent facial anatomy",
        ],
        "performance": [
            "energetic performance framing",
            "stage-like confidence",
            "dynamic camera movement",
            "strong visual rhythm",
        ],
        "abstract": [
            "stylized visual poetry",
            "bold color contrast",
            "symbolic scene design",
            "surreal but coherent motion",
        ],
        "brand-promo": [
            "commercial-grade polish",
            "clean premium aesthetic",
            "product storytelling energy",
            "ad-ready lighting",
        ],
    }
    return mapping[style_preset]


def _section_descriptor(section_label: str) -> str:
    label = section_label.lower()
    if label == "intro":
        return "establishing shot with atmosphere and anticipation"
    if label == "verse":
        return "narrative medium shot with subtle movement"
    if label == "pre-chorus":
        return "rising tension with forward camera drift"
    if label == "chorus":
        return "hero shot, strong subject clarity, expressive motion"
    if label == "bridge":
        return "contrast section with unexpected angle and mood shift"
    if label == "outro":
        return "closing shot with graceful deceleration"
    return "stylized music video shot with clear subject and coherent action"


def _build_prompt(
    rng: random.Random,
    theme: str,
    style_preset: str,
    section_label: str,
    brand: str,
) -> str:
    camera_moves = [
        "slow dolly-in",
        "handheld parallax motion",
        "gentle crane rise",
        "tracking shot from side profile",
        "center-framed push-in",
        "over-shoulder reveal",
    ]
    style_tokens = _style_tokens(style_preset)
    descriptor = _section_descriptor(section_label)
    camera = rng.choice(camera_moves)
    style = ", ".join(rng.sample(style_tokens, k=min(3, len(style_tokens))))
    brand_clause = ""
    if brand.strip():
        brand_clause = f", subtle visual motif inspired by {brand.strip()}, no readable logos or text"
    return (
        f"music video scene, {theme.strip()}, {descriptor}, {camera}, {style}, "
        f"clear human subject, coherent anatomy, cinematic realism{brand_clause}"
    )


def _negative_prompt() -> str:
    return (
        "text, logo, watermark, unreadable typography, blurry, overexposed, underexposed, "
        "gray blob, abstract texture mush, deformed anatomy, extra limbs, flicker, jitter"
    )


def _quality_hint(shot_kind: str) -> str:
    # Music-video defaults bias toward visual quality over throughput.
    return "quality"


def _takes_for_kind(shot_kind: str, args: argparse.Namespace) -> int:
    if shot_kind == "hero":
        return max(1, args.takes_hero)
    if shot_kind == "standard":
        return max(1, args.takes_standard)
    return max(1, args.takes_filler)


def _build_shots(analysis: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    duration_seconds = float(analysis.get("duration_seconds", 0.0) or 0.0)
    if duration_seconds <= 0:
        raise ValueError("Analysis file missing valid duration_seconds")

    beats = [float(value) for value in analysis.get("beats", []) if float(value) >= 0.0]
    bpm = float(analysis.get("bpm", 120.0) or 120.0)
    sections = analysis.get("sections", [])
    if not isinstance(sections, list):
        sections = []

    beat_sec = _beat_interval(beats, bpm)
    rng = random.Random(args.seed)
    cursor = 0.0
    shot_index = 1
    shots: list[dict[str, Any]] = []

    while cursor < duration_seconds - 0.1:
        section = _find_section_at(cursor, sections)
        section_label = str(section.get("label", "section"))
        energy = str(section.get("energy", "medium"))
        shot_kind = _shot_type(section_label, energy, shot_index)

        if shot_kind == "hero":
            beats_per_shot = 4
        elif shot_kind == "standard":
            beats_per_shot = 6
        else:
            beats_per_shot = 8
        raw_duration = beats_per_shot * beat_sec
        shot_duration = max(float(args.min_shot_seconds), min(float(args.max_shot_seconds), raw_duration))
        target_end = cursor + shot_duration
        snapped_end = _snap_forward(target_end, beats) if beats else target_end
        end_sec = min(duration_seconds, max(cursor + args.min_shot_seconds, snapped_end))
        if end_sec - cursor > args.max_shot_seconds:
            end_sec = min(duration_seconds, cursor + args.max_shot_seconds)
        if end_sec <= cursor:
            end_sec = min(duration_seconds, cursor + max(beat_sec, args.min_shot_seconds))

        prompt = _build_prompt(
            rng=rng,
            theme=args.theme,
            style_preset=args.style_preset,
            section_label=section_label,
            brand=args.brand,
        )
        shot = {
            "id": f"shot_{shot_index:03d}",
            "start_sec": round(cursor, 4),
            "end_sec": round(end_sec, 4),
            "duration_sec": round(end_sec - cursor, 4),
            "section": section_label,
            "energy": energy,
            "priority": shot_kind,
            "visual_goal": _section_descriptor(section_label),
            "prompt": prompt,
            "negative_prompt": _negative_prompt(),
            "quality_hint": _quality_hint(shot_kind),
            "takes": _takes_for_kind(shot_kind, args),
            "transition_after": "cut",
        }
        shots.append(shot)
        cursor = end_sec
        shot_index += 1

    # Avoid tiny tail shots by merging the final fragment into previous shot.
    if len(shots) >= 2:
        tail = shots[-1]
        if float(tail.get("duration_sec", 0.0) or 0.0) < float(args.min_shot_seconds):
            previous = shots[-2]
            previous["end_sec"] = tail["end_sec"]
            previous["duration_sec"] = round(
                float(previous.get("end_sec", 0.0)) - float(previous.get("start_sec", 0.0)),
                4,
            )
            shots.pop()

    return shots


def main() -> int:
    try:
        args = _parse_args()
        analysis_path = Path(args.analysis).expanduser().resolve()
        if not analysis_path.exists():
            raise FileNotFoundError(f"Analysis file not found: {analysis_path}")

        analysis = _load_json(analysis_path)
        shots = _build_shots(analysis, args)
        output_path = _resolve_output_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "status": "success",
            "analysis_file": str(analysis_path),
            "plan_file": str(output_path),
            "theme": args.theme,
            "brand": args.brand,
            "style_preset": args.style_preset,
            "resolution": args.resolution,
            "fps": args.fps,
            "duration_seconds": float(analysis.get("duration_seconds", 0.0) or 0.0),
            "bpm": float(analysis.get("bpm", 120.0) or 120.0),
            "shots": shots,
            "summary": {
                "total_shots": len(shots),
                "hero_shots": sum(1 for shot in shots if shot.get("priority") == "hero"),
                "standard_shots": sum(1 for shot in shots if shot.get("priority") == "standard"),
                "filler_shots": sum(1 for shot in shots if shot.get("priority") == "filler"),
            },
        }
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
