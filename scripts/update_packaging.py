#!/usr/bin/env python3
"""Bump the packaging manifests (winget + scoop) to a released version.

Downloads SHA256SUMS from the GitHub release of the given tag, pulls the
Windows installer's hash out of it, and rewrites the four manifest files
under packaging/ (winget version/installer/locale + scoop json). Pure
stdlib -- no pip install needed, same as check_version.py.

Nothing is submitted anywhere: review the diff, then validate + submit
yourself per packaging/README.md.

Usage:
    python scripts/update_packaging.py           # tag = v<contents of VERSION>
    python scripts/update_packaging.py v2.3.0    # explicit tag
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Teerapat-Vatpitak/thai-pii-redaction"


def installer_name(version: str) -> str:
    return f"AI.Guard_{version}_x64-setup.exe"


def fetch_text(url: str) -> str:
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: could not fetch {url}: {e}")


def fetch_sums(tag: str) -> str:
    return fetch_text(f"https://github.com/{REPO}/releases/download/{tag}/SHA256SUMS")


def fetch_release_date(tag: str) -> str:
    """YYYY-MM-DD the release was published (winget's ReleaseDate field)."""
    body = fetch_text(f"https://api.github.com/repos/{REPO}/releases/tags/{tag}")
    published = json.loads(body).get("published_at") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}T", published):
        sys.exit(f"ERROR: release {tag} has no published_at -- is it published (not a draft)?")
    return published[:10]


def parse_hash(sums_text: str, filename: str) -> str:
    """Find `<hash>  <filename>` (sha256sum format; `*` binary marker tolerated)."""
    for line in sums_text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.*)$", line.strip())
        if m and m.group(2) == filename:
            return m.group(1).lower()
    sys.exit(f"ERROR: {filename} not found in SHA256SUMS")


def _sub_exactly(pattern: str, repl: str, text: str, name: str) -> str:
    """re.subn that demands exactly one match -- layout drift fails loudly
    before anything is written (plan_writes computes all rewrites first)."""
    new_text, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n != 1:
        sys.exit(
            f"ERROR: {name}: pattern {pattern!r} matched {n}x (expected exactly 1) "
            "-- manifest layout changed; nothing was written"
        )
    return new_text


def plan_writes(
    root: Path, version: str, sha256: str, release_date: str
) -> list[tuple[Path, str]]:
    """Compute every rewrite up front; sys.exit (writing nothing) on mismatch."""
    winget = root / "packaging" / "winget"
    scoop_path = root / "packaging" / "scoop" / "aiguard.json"
    url = f"https://github.com/{REPO}/releases/download/v{version}/{installer_name(version)}"
    writes: list[tuple[Path, str]] = []

    for fname in (
        "Teerapat-Vatpitak.AIGuard.yaml",
        "Teerapat-Vatpitak.AIGuard.locale.en-US.yaml",
    ):
        path = winget / fname
        text = _sub_exactly(
            r"^PackageVersion: .+$",
            f"PackageVersion: {version}",
            path.read_text(encoding="utf-8"),
            fname,
        )
        writes.append((path, text))

    inst_path = winget / "Teerapat-Vatpitak.AIGuard.installer.yaml"
    text = inst_path.read_text(encoding="utf-8")
    text = _sub_exactly(r"^PackageVersion: .+$", f"PackageVersion: {version}", text, inst_path.name)
    text = _sub_exactly(r"^ReleaseDate: .+$", f"ReleaseDate: {release_date}", text, inst_path.name)
    text = _sub_exactly(r"^    DisplayVersion: .+$", f"    DisplayVersion: {version}", text, inst_path.name)
    text = _sub_exactly(r"^    InstallerUrl: .+$", f"    InstallerUrl: {url}", text, inst_path.name)
    text = _sub_exactly(
        r"^    InstallerSha256: .+$",
        f"    InstallerSha256: {sha256.upper()}",
        text,
        inst_path.name,
    )
    writes.append((inst_path, text))

    data = json.loads(scoop_path.read_text(encoding="utf-8"))
    try:
        data["version"] = version
        data["architecture"]["64bit"]["url"] = url + "#/dl.7z"
        data["architecture"]["64bit"]["hash"] = sha256.lower()
    except (KeyError, TypeError):
        sys.exit(
            f"ERROR: {scoop_path.name}: expected keys missing -- manifest layout "
            "changed; nothing was written"
        )
    writes.append((scoop_path, json.dumps(data, indent=4, ensure_ascii=False) + "\n"))
    return writes


def main() -> None:
    tag = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "v" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    )
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        sys.exit(f"ERROR: tag {tag!r} does not look like vX.Y.Z")
    version = tag[1:]
    sha256 = parse_hash(fetch_sums(tag), installer_name(version))
    release_date = fetch_release_date(tag)
    for path, text in plan_writes(ROOT, version, sha256, release_date):
        path.write_text(text, encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    print(f"\n{tag}: installer sha256 {sha256}")
    print("Review the diff, then validate + submit per packaging/README.md.")


if __name__ == "__main__":
    main()
