"""Archive entries: loading notes, the public/private split, and display helpers.

The air gap lives in `publicize`: the public build only ever sees the copies it
returns, which contain public entries alone, with private fields and private
comments (%% ... %%, including any images inside them) removed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import Collection, Config
from .dates import When, parse_when
from .markup import strip_private

# Fields with dedicated handling; everything else is shown as a fact on the entry page.
RESERVED = {
    "title", "date", "dates", "public", "tags", "image", "link", "favourite", "favorite",
    "rating", "share_images", "aliases", "cssclasses", "slug", "summary", "status", "caption",
}
# Never published, whatever the collection config says.
ALWAYS_PRIVATE = {"with", "private", "caption"}
# Statuses that keep an entry out of the feed (still in the library).
NOT_IN_FEED = {"want", "reading", "watching", "listening"}

FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
WIKILINK_VALUE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


@dataclass
class Entry:
    collection: Collection
    source: Path
    stem: str
    slug: str
    fields: dict
    body: str
    title: str
    when: When | None
    extra: list[When] = field(default_factory=list)
    public: bool = False
    rating: float | None = None
    favourite: bool = False
    link: str | None = None
    image: str | None = None
    caption: str | None = None
    tags: list[str] = field(default_factory=list)
    status: str | None = None
    summary: str | None = None

    @property
    def url(self) -> str:
        return f"/{self.collection.key}/{self.slug}/"

    @property
    def in_feed(self) -> bool:
        return self.collection.in_feed and self.when is not None and (self.status or "") not in NOT_IN_FEED

    @property
    def sort_key(self) -> tuple:
        return (self.when.day if self.when else date.min, self.title.lower())

    @property
    def meta_line(self) -> str:
        """'Celine Song, 2023 · Prince Charles Cinema' from the collection's meta/location fields."""
        meta = ", ".join(v for v in (display(self.fields.get(f)) for f in self.collection.meta) if v)
        where = ", ".join(v for v in (display(self.fields.get(f)) for f in self.collection.location) if v)
        return " · ".join(part for part in (meta, where) if part)

    @property
    def feed_title(self) -> str:
        verb = self.collection.verb or self.collection.kind.capitalize()
        return f"{verb} {self.title}" + (f" ({self.meta_line})" if self.meta_line else "")

    def value(self, name: str) -> str:
        if name == "rating":
            return stars(self.rating)
        if name == "status":
            return self.status or ""
        if name == "summary":
            return self.summary or ""
        return display(self.fields.get(name))

    def facts(self) -> list[tuple[str, str]]:
        """(label, value) pairs for the entry page: fields not already in the subtitle."""
        c = self.collection
        in_subtitle = set(c.meta) | set(c.location)
        order = list(dict.fromkeys([*c.columns, *self.fields]))
        out = []
        for name in order:
            if name in RESERVED or name in in_subtitle or name not in self.fields:
                continue
            text = display(self.fields[name])
            if text:
                out.append((label(name), text))
        if self.status:
            out.append(("Status", self.status))
        return out


def read_note(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("front matter is not a key: value mapping")
    return data, text[m.end():]


def load_archive(cfg: Config) -> tuple[list[Entry], list[str]]:
    """Every note in every collection folder. Folders and files starting with '.' or '_' are skipped."""
    if cfg.archive is None:
        return [], ["No archive configured: building without the feed."]
    if not cfg.archive.is_dir():
        return [], [f"Archive not found at {cfg.archive}: building without the feed."]
    entries, warnings = [], []
    for key, collection in cfg.collections.items():
        folder = cfg.archive / key
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.md")):
            if any(part.startswith((".", "_")) for part in path.relative_to(cfg.archive).parts):
                continue
            try:
                fields, body = read_note(path)
                entries.append(make_entry(collection, path, fields, body))
            except Exception as exc:  # one bad note shouldn't break the site
                warnings.append(f"Skipped {path.relative_to(cfg.archive)}: {exc}")
    assign_slugs(entries)
    return entries, warnings


def make_entry(collection: Collection, path: Path, fields: dict, body: str) -> Entry:
    extra = fields.get("dates") or []
    if not isinstance(extra, list):
        extra = [extra]
    rating = fields.get("rating")
    return Entry(
        collection=collection,
        source=path,
        stem=path.stem,
        slug="",
        fields=fields,
        body=body,
        title=str(fields.get("title") or path.stem).strip(),
        when=parse_when(fields.get("date")),
        extra=sorted(w for w in (parse_when(d) for d in extra) if w),
        public=fields.get("public") is True,
        rating=float(rating) if isinstance(rating, (int, float)) and not isinstance(rating, bool) else None,
        favourite=bool(fields.get("favourite") or fields.get("favorite")),
        link=str(fields["link"]) if fields.get("link") else None,
        image=str(fields["image"]) if fields.get("image") else None,
        caption=str(fields["caption"]) if fields.get("caption") else None,
        tags=[str(t) for t in (fields.get("tags") or [])] if isinstance(fields.get("tags"), list) else [],
        status=str(fields["status"]).strip().lower() if fields.get("status") else None,
        summary=str(fields["summary"]) if fields.get("summary") else None,
    )


def assign_slugs(entries: list[Entry]) -> None:
    seen: set[tuple[str, str]] = set()
    for e in sorted(entries, key=lambda e: (e.collection.key, str(e.source))):
        base = slugify(str(e.fields.get("slug") or e.stem))
        slug, n = base, 2
        while (e.collection.key, slug) in seen:
            slug, n = f"{base}-{n}", n + 1
        seen.add((e.collection.key, slug))
        e.slug = slug


def publicize(entries: list[Entry]) -> list[Entry]:
    """Sanitised copies of the public entries: the only thing the public build sees."""
    out = []
    for e in entries:
        if e.public is not True:
            continue
        hidden = ALWAYS_PRIVATE | set(e.collection.private)
        out.append(
            replace(
                e,
                fields={k: v for k, v in e.fields.items() if k not in hidden},
                body=strip_private(e.body),
                image=None if "image" in hidden else e.image,
                caption=None if "caption" in hidden else e.caption,
                # fields parsed into attributes must be hidden there too
                rating=None if "rating" in hidden else e.rating,
                link=None if "link" in hidden else e.link,
                favourite=False if hidden & {"favourite", "favorite"} else e.favourite,
                status=None if "status" in hidden else e.status,
                summary=None if "summary" in hidden else e.summary,
                tags=[] if "tags" in hidden else list(e.tags),
                extra=[] if "dates" in hidden else list(e.extra),
            )
        )
    return out


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-") or "untitled"


def label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def display(value) -> str:
    """Plain-text rendering of a front-matter value."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(v for v in (display(x) for x in value) if v)
    if isinstance(value, (date, datetime)):
        return parse_when(value).long
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return WIKILINK_VALUE.sub(lambda m: m.group(2) or m.group(1), str(value)).strip()


def stars(rating: float | None) -> str:
    if rating is None or rating <= 0:
        return ""
    whole, half = int(rating), (rating % 1) >= 0.5
    return "★" * whole + ("½" if half else "")
