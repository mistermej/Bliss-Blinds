"""Snapshot the current integration into a version folder.

Every version bump produces a flat copy of the integration under
``C:\\omniroute\\bliss_blinds_versions\\<version>\\`` — the same layout as the
existing 0.1.1 / 0.1.2 folders (flat files + a ``brand/`` folder for HACS
icons). Run this from the project root.

Usage:
    python build_version.py            snapshot using the version already in
                                       manifest.json (no bump)
    python build_version.py 0.1.3      bump manifest.json to 0.1.3 AND snapshot
    python build_version.py --next     auto-bump the highest existing version
                                       (0.1.2 -> 0.1.3) AND snapshot
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "custom_components" / "bliss_blinds"
MANIFEST = SRC / "manifest.json"
VERSIONS_DIR = Path(r"C:\omniroute\bliss_blinds_versions")

# Files that form the release — deliberately not __pycache__ or dev docs.
INTEGRATION_FILES = (
    "__init__.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "cover.py",
    "manifest.json",
    "protocol.py",
    "sensor.py",
    "strings.json",
)

GITHUB_MANIFEST = "https://github.com/mistermej/bliss_blinds"


def current_version() -> str:
    return str(json.loads(MANIFEST.read_text())["version"])


def set_manifest_version(version: str) -> None:
    data = json.loads(MANIFEST.read_text())
    data["version"] = version
    MANIFEST.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def highest_existing() -> tuple[int, int, int]:
    """Find the highest MAJOR.MINOR.PATCH among version folders (0.0.0 if none)."""
    best = (0, 0, 0)
    for folder in VERSIONS_DIR.glob("*.*.*"):
        if not folder.is_dir():
            continue
        try:
            parts = tuple(int(p) for p in folder.name.split("."))
        except ValueError:
            continue
        if len(parts) == 3 and parts > best:
            best = parts  # type: ignore[assignment]
    return best  # type: ignore[return-value]


def bump(version: str) -> str:
    major, minor, patch = (int(p) for p in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def copy_brand(version_dir: Path) -> None:
    """brand/ from the source wins; otherwise carry the newest one forward."""
    brand_src = SRC / "brand"
    if brand_src.is_dir():
        target = version_dir / "brand"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(brand_src, target)
        print(f"  copied brand/ from source ({len(list(target.iterdir()))} file(s))")
        return
    for folder in sorted(VERSIONS_DIR.glob("*.*.*"), reverse=True):
        if folder == version_dir:
            continue
        previous = folder / "brand"
        if previous.is_dir():
            shutil.copytree(previous, version_dir / "brand")
            print(f"  carried brand/ forward from {folder.name}/")
            return
    print("  (no brand/ folder — drop brand/icon.png + brand/logo.png for HACS branding)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot the integration into a version folder.")
    parser.add_argument("--next", action="store_true", help="auto-bump the highest existing version")
    parser.add_argument("version", nargs="?", help="version to snapshot (default: manifest version)")
    args = parser.parse_args()

    if args.next:
        version = bump(".".join(str(p) for p in highest_existing()))
    else:
        version = args.version or current_version()

    # Keep manifest.json in lock-step whenever a new version is named.
    if version != current_version():
        set_manifest_version(version)
        print(f"  manifest.json version -> {version}")

    version_dir = VERSIONS_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)

    print(f"Snapshoting {version} into {version_dir}")
    for name in INTEGRATION_FILES:
        source = SRC / name
        if not source.exists():
            print(f"  !! missing {name} — skipped (release is incomplete!)")
            continue
        shutil.copy2(source, version_dir / name)
        print(f"  copied {name}")

    copy_brand(version_dir)

    print(f"Done. Folder: {version_dir}")
    print(f"Change entry not yet in CHANGELOG.md - write one for {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())