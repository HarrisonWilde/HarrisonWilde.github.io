"""Load site.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Folders inside this (public) repository that may hold an archive: sample data only.
SAMPLE_DIRS = (ROOT / "examples", ROOT / "tests")


@dataclass(frozen=True)
class Collection:
    key: str
    label: str
    kind: str
    verb: str
    date_label: str
    italic: bool
    meta: tuple[str, ...]
    location: tuple[str, ...]
    columns: tuple[str, ...]
    private: tuple[str, ...]
    in_feed: bool


@dataclass(frozen=True)
class Config:
    title: str
    description: str
    url: str
    lang: str
    links: tuple[tuple[str, str], ...]
    archive: Path | None
    collections: dict[str, Collection]
    private_server: dict
    cloudflare: dict


def load(path: Path = ROOT / "site.yaml", archive: str | Path | None = None) -> Config:
    """Read site.yaml. An explicit `archive` (e.g. from --archive) resolves against the cwd."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    collections = {
        key: Collection(
            key=key,
            label=c.get("label", key.title()),
            kind=c.get("kind", key),
            verb=c.get("verb", ""),
            date_label=c.get("date_label", "date"),
            italic=bool(c.get("italic", False)),
            meta=tuple(c.get("meta") or ()),
            location=tuple(c.get("location") or ()),
            columns=tuple(c.get("columns") or ()),
            private=tuple(c.get("private") or ()),
            in_feed=bool(c.get("in_feed", True)),
        )
        for key, c in (raw.get("collections") or {}).items()
    }
    if archive is not None:
        archive_path = Path(archive).expanduser().resolve()
    elif raw.get("archive"):
        archive_path = Path(raw["archive"]).expanduser()
        if not archive_path.is_absolute():
            archive_path = (path.parent / archive_path).resolve()
    else:
        archive_path = None
    if archive_path is not None:
        check_archive_location(archive_path)
    return Config(
        title=raw["title"],
        description=raw.get("description", ""),
        url=raw.get("url", "").rstrip("/"),
        lang=raw.get("lang", "en"),
        links=tuple((name, url) for name, url in raw.get("links") or ()),
        archive=archive_path,
        collections=collections,
        private_server=raw.get("private_server") or {},
        cloudflare=raw.get("cloudflare") or {},
    )


def check_archive_location(archive: Path) -> None:
    """Refuse a real archive inside this repository: everything in it is public on GitHub."""
    if archive.is_relative_to(ROOT) and not any(archive.is_relative_to(d) for d in SAMPLE_DIRS):
        raise SystemExit(
            f"The archive at {archive} is inside this repository, which is public.\n"
            "Keep it outside (e.g. an iCloud Obsidian vault) and point site.yaml or --archive at it."
        )


def is_sample(archive: Path | None) -> bool:
    return archive is not None and any(archive.is_relative_to(d) for d in SAMPLE_DIRS)
