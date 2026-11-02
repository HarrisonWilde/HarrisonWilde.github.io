"""Import exports from other services into the archive.

Every imported note is private (`public: false`). Existing notes are never
overwritten, and anything already in the archive (same title and year, author
or place) is skipped, so re-running an import is safe. Without --write this is
a dry run that only reports what it would do.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import Config
from ..entries import read_note


@dataclass
class Note:
    collection: str
    filename: str  # without .md
    fields: dict
    body: str = ""
    key: tuple = field(default_factory=tuple)  # identity for de-duplication


def run_import(cfg: Config, source: str, path: Path, write: bool) -> None:
    from . import books, gmaps, letterboxd

    if cfg.archive is None:
        raise SystemExit("No archive configured: set `archive` in site.yaml or pass --archive.")
    if not path.exists():
        raise SystemExit(f"Not found: {path}")
    readers = {"letterboxd": letterboxd.read, "goodreads": books.read, "storygraph": books.read, "gmaps": gmaps.read}
    notes = readers[source](path)
    if not notes:
        raise SystemExit(f"Found nothing to import in {path}. Is it the right export?")

    created, skipped = [], []
    by_collection: dict[str, list[Note]] = {}
    for n in notes:
        by_collection.setdefault(n.collection, []).append(n)
    for collection, items in by_collection.items():
        folder = cfg.archive / collection
        known = existing_keys(folder, KEYS[collection])
        taken = {p.stem.lower() for p in folder.glob("*.md")} if folder.is_dir() else set()
        for n in items:
            if n.key and n.key in known:
                skipped.append(n)
                continue
            name = unique_name(n, taken)
            taken.add(name.lower())
            known.add(n.key)
            created.append((folder / f"{name}.md", n))

    for target, n in created:
        print(f"  + {target.relative_to(cfg.archive)}")
    print(f"{len(created)} new notes, {len(skipped)} already in the archive.")
    if not write:
        print("Dry run: nothing written. Re-run with --write to create these notes (all private).")
        return
    for target, n in created:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(note_text(n.fields, n.body), encoding="utf-8")
    print(f"Wrote {len(created)} notes to {cfg.archive}.")


# ---------- identity ----------


def norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


KEYS = {
    "films": lambda f: ("film", norm(f.get("title")), str(f.get("year") or "")),
    "books": lambda f: ("book", norm(f.get("title")), norm(f.get("author"))),
    "places": lambda f: ("place", norm(f.get("title")), norm(f.get("city"))),
}


def existing_keys(folder: Path, key) -> set:
    keys = set()
    if folder.is_dir():
        for p in folder.rglob("*.md"):
            try:
                fields, _ = read_note(p)
            except Exception:
                continue
            fields.setdefault("title", p.stem)
            keys.add(key(fields))
    return keys


# ---------- writing ----------

UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]+')


def safe_filename(text: str) -> str:
    name = UNSAFE.sub("-", text).strip(" .-")
    return re.sub(r"\s+", " ", name)[:120] or "Untitled"


def unique_name(n: Note, taken: set[str]) -> str:
    name = safe_filename(n.filename)
    if name.lower() not in taken:
        return name
    for extra in (n.fields.get("author"), n.fields.get("city"), n.fields.get("year")):
        if extra:
            candidate = safe_filename(f"{n.filename} ({extra})")
            if candidate.lower() not in taken:
                return candidate
    i = 2
    while f"{name} {i}".lower() in taken:
        i += 1
    return f"{name} {i}"


def note_text(fields: dict, body: str = "") -> str:
    clean = {k: v for k, v in fields.items() if v not in (None, "", [], {}) or k == "public"}
    front = yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)
    return f"---\n{front}---\n" + (body.strip() + "\n" if body.strip() else "")


# ---------- reading exports ----------


def export_files(path: Path) -> dict[str, str]:
    """Text of every CSV/JSON file in a .zip, a folder, or a single file, keyed by relative path."""
    files: dict[str, str] = {}
    wanted = (".csv", ".json")
    if path.is_dir():
        for p in path.rglob("*"):
            if p.is_file() and p.suffix.lower() in wanted:
                files[p.relative_to(path).as_posix()] = p.read_bytes().decode("utf-8-sig", errors="replace")
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(wanted) and not name.startswith("__MACOSX"):
                    files[name] = z.read(name).decode("utf-8-sig", errors="replace")
    else:
        files[path.name] = path.read_bytes().decode("utf-8-sig", errors="replace")
    return files


def csv_rows(text: str) -> list[dict]:
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def html_to_markdown(text: str) -> str:
    """Reviews from Letterboxd and Goodreads arrive as light HTML."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
    text = re.sub(r"</?(i|em)>", "*", text, flags=re.I)
    text = re.sub(r"</?(b|strong)>", "**", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").strip()
