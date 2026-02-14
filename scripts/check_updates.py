#!/usr/bin/env python3
"""
Check for Wan2GP updates and summarize release changes.

Usage:
  python scripts/check_updates.py
  python scripts/check_updates.py --wan-root E:/tools/Wan2GP
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Check Wan2GP updates")
    parser.add_argument("--repo", default="deepbeepmeep/Wan2GP", help="GitHub repo in owner/name form")
    parser.add_argument("--wan-root", help="Local Wan2GP root path to compare installed version")
    parser.add_argument("--max-highlights", type=int, default=8, help="Max highlighted changes to return")
    return parser.parse_args()


def _fetch_json(url: str) -> Any:
    """Fetch JSON from GitHub API endpoint."""
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "wan2gp-operator"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_latest_release(repo: str) -> dict[str, Any]:
    """Fetch latest GitHub release metadata, with tag fallback."""
    release_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        release = _fetch_json(release_url)
        return {
            "version": str(release.get("tag_name") or release.get("name") or ""),
            "published_at": release.get("published_at"),
            "url": release.get("html_url"),
            "body": release.get("body") or "",
            "source": "release",
        }
    except HTTPError as exc:
        if exc.code != 404:
            raise

    # Fallback to tags when no formal release exists.
    tags_url = f"https://api.github.com/repos/{repo}/tags"
    tags = _fetch_json(tags_url)
    if isinstance(tags, list) and tags:
        top = tags[0]
        return {
            "version": str(top.get("name", "")),
            "published_at": None,
            "url": f"https://github.com/{repo}/tree/{top.get('name','')}",
            "body": "",
            "source": "tag",
        }

    # Fallback to README version scraping for repos that publish updates there.
    readme_url = f"https://raw.githubusercontent.com/{repo}/main/README.md"
    request = Request(readme_url, headers={"User-Agent": "wan2gp-operator"})
    with urlopen(request, timeout=20) as response:
        readme_text = response.read().decode("utf-8", errors="replace")
    match = re.search(r"WanGP\s+v?(\d+(?:\.\d+)*)", readme_text, flags=re.IGNORECASE)
    if match:
        version = match.group(1)
        section_lines: list[str] = []
        lines = readme_text.splitlines()
        start_idx = None
        for i, line in enumerate(lines):
            if "latest updates" in line.lower():
                start_idx = i
                break
        if start_idx is not None:
            for line in lines[start_idx + 1 :]:
                if line.startswith("## ") and section_lines:
                    break
                section_lines.append(line)
        section_text = "\n".join(section_lines[:220]).strip()

        return {
            "version": version,
            "published_at": None,
            "url": f"https://github.com/{repo}",
            "body": section_text,
            "source": "readme",
        }

    raise RuntimeError("No releases, tags, or detectable README version found for repository.")


def _extract_local_version(wan_root: Path) -> str | None:
    """Extract WanGP_version from local wgp.py."""
    wgp_file = wan_root / "wgp.py"
    if not wgp_file.exists():
        return None
    content = wgp_file.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'WanGP_version\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else None


def _version_tuple(version_str: str | None) -> tuple[int, ...]:
    """Convert version-like strings to integer tuples for loose comparison."""
    if not version_str:
        return ()
    parts = re.findall(r"\d+", version_str)
    return tuple(int(p) for p in parts)


def _normalize_lines(markdown_text: str, max_highlights: int) -> list[str]:
    """Extract plain-language highlights from release markdown."""
    highlights: list[str] = []
    for line in markdown_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith(("#", "*", "-", "•")):
            cleaned = cleaned.lstrip("#*-• ").strip()
        if len(cleaned) < 8:
            continue
        if cleaned.lower().startswith("update"):
            continue
        if cleaned not in highlights:
            highlights.append(cleaned)
        if len(highlights) >= max_highlights:
            break
    return highlights


def main() -> int:
    """CLI entrypoint."""
    args = _parse_args()

    try:
        latest = _fetch_latest_release(args.repo)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(json.dumps({"status": "error", "error": f"Failed to fetch release info: {exc}"}, indent=2), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    remote_version = latest["version"]
    remote_url = latest["url"]
    remote_published_at = latest["published_at"]
    remote_body = latest["body"]
    highlights = _normalize_lines(remote_body, args.max_highlights)

    local_version = None
    update_available = None
    local_root = None
    local_warning = None
    if args.wan_root:
        local_root = Path(args.wan_root).expanduser().resolve()
        if not (local_root / "wgp.py").exists():
            local_warning = "Provided --wan-root does not look like a Wan2GP root (missing wgp.py)."
        else:
            local_version = _extract_local_version(local_root)
            update_available = _version_tuple(remote_version) > _version_tuple(local_version)

    report: dict[str, Any] = {
        "status": "success",
        "repo": args.repo,
        "latest_release": {
            "version": remote_version,
            "published_at": remote_published_at,
            "url": remote_url,
            "source": latest["source"],
        },
        "highlights": highlights,
        "local": {
            "wan_root": str(local_root) if local_root else None,
            "version": local_version,
            "update_available": update_available,
            "warning": local_warning,
        },
    }

    if local_root and update_available and not local_warning:
        report["suggested_update_commands"] = [
            f'git -C "{local_root}" pull --ff-only',
            f'pip install -r "{local_root}\\requirements.txt"',
        ]

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
