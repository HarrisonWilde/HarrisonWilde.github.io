"""Set up an Obsidian vault for the archive from vault-template/, without overwriting anything."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import config

TEMPLATE = config.ROOT / "vault-template"
MERGED = {".obsidian/types.json", ".obsidian/templates.json"}  # merged into existing settings


def init_vault(path: Path) -> None:
    path = path.resolve()
    config.check_archive_location(path)
    if not path.is_dir():  # let Obsidian create it, so iCloud treats it as a vault
        raise SystemExit(
            f"{path} doesn't exist yet.\n"
            "Create the vault in Obsidian first (Create new vault → name it → Store in iCloud on),\n"
            "give iCloud a minute to bring it to this Mac, then run this again."
        )
    cfg = config.load()
    added = []
    for key in cfg.collections:
        folder = path / key
        if not folder.exists():
            folder.mkdir()
            added.append(f"{key}/")
    for src in sorted(TEMPLATE.rglob("*")):
        if not src.is_file() or src.name == ".DS_Store":
            continue
        rel = src.relative_to(TEMPLATE).as_posix()
        dest = path / rel
        if rel in MERGED and dest.exists():
            if merge_json(src, dest):
                added.append(f"{rel} (merged)")
            continue
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        added.append(rel)
    print(f"Vault at {path}")
    for a in added:
        print(f"  + {a}")
    if not added:
        print("  already set up; nothing changed")
    if cfg.archive != path:
        print(f"\nsite.yaml points `archive` at {cfg.archive}.\nChange it to {path} to build from this vault.")


def merge_json(src: Path, dest: Path) -> bool:
    """Add our keys to an existing Obsidian settings file, keeping every setting already there."""
    ours, theirs = json.loads(src.read_text()), json.loads(dest.read_text() or "{}")
    if "types" in ours:
        types = theirs.setdefault("types", {})
        new = {k: v for k, v in ours["types"].items() if k not in types}
        types.update(new)
        changed = bool(new)
    else:
        changed = any(k not in theirs for k in ours)
        for k, v in ours.items():
            theirs.setdefault(k, v)
    if changed:
        dest.write_text(json.dumps(theirs, indent=2) + "\n")
    return changed
