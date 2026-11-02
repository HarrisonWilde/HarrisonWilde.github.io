"""Publications: scraped data (data/publications.json) plus hand edits (data/publications.yaml)."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path

import yaml


@dataclass
class Publication:
    title: str
    authors: list[str]
    year: int | None
    venue: str
    venue_full: str
    link: str | None
    note: str | None  # Markdown
    date: str | None = None  # Scholar's "2021/3/18", "2021/1" or "2021"

    def authors_html(self, me: set[str], limit: int = 8) -> str:
        """All authors when there are few; otherwise the first five, you, and the last."""

        def show(name: str) -> str:
            return f"<b>{escape(name)}</b>" if name in me else escape(name)

        names = self.authors
        if len(names) <= limit:
            return ", ".join(show(a) for a in names)
        parts = [show(a) for a in names[:5]]
        mine = next((i for i, a in enumerate(names) if a in me), None)
        if mine is not None and 5 <= mine < len(names) - 1:
            parts += ["…", show(names[mine])]
        parts += ["…", show(names[-1])]
        return ", ".join(parts)


def load(root: Path) -> tuple[list[Publication], dict]:
    """Scholar's papers plus Nesta articles (skipping any Scholar already has), with hand edits applied."""
    scholar, nesta = read_json(root / "data" / "publications.json"), read_json(root / "data" / "nesta.json")
    edits_path = root / "data" / "publications.yaml"
    edits = (yaml.safe_load(edits_path.read_text(encoding="utf-8")) if edits_path.exists() else None) or {}
    venues = {k.lower(): v for k, v in (edits.get("venues") or {}).items()}
    papers = edits.get("papers") or {}
    me = set(edits.get("me") or ["Harrison Wilde"])

    records = list(scholar.get("publications", []))
    seen = {norm(r["title"]) for r in records}
    nesta_titles = {norm(a["title"]) for a in nesta.get("articles", [])}
    for a in nesta.get("articles", []):
        if norm(a["title"]) not in seen:
            records.append({
                "title": a["title"],
                "authors": a.get("authors", []),
                "year": int(a["date"][:4]) if a.get("date") else None,
                "venue": f"Nesta {a['kind'].lower()}" if a.get("kind") else "Nesta",
                "link": a.get("link"),
                "date": a.get("date"),
            })

    pubs = []
    for p in records:
        edit = next((e for key, e in papers.items() if key.lower() in p["title"].lower()), None) or {}
        if edit.get("hide"):
            continue
        renames = edit.get("rename_authors") or {}
        venue_full = edit.get("venue") or p.get("journal") or p.get("venue") or ""
        link = edit.get("link", p.get("link"))
        if link and "scholar.google." in link:  # Scholar links to itself when it has nothing better
            link = None
        authors = [renames.get(a, a) for a in edit.get("authors", p.get("authors", []))]
        if norm(p["title"]) in nesta_titles:  # Nesta's author order is arbitrary, so I go first
            authors.sort(key=lambda name: name not in me)
        pubs.append(
            Publication(
                title=edit.get("title", p["title"]),
                authors=authors,
                year=edit.get("year", p.get("year")),
                venue=edit.get("venue") or short_venue(venue_full, venues),
                venue_full=venue_full,
                link=link,
                note=edit.get("note"),
                date=str(edit.get("date", p.get("date") or "")) or None,
            )
        )
    meta = {"me": me}
    return pubs, meta


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def short_venue(venue: str, venues: dict[str, str]) -> str:
    """'BMC medicine 19 (1), 213, 2021' -> 'BMC Medicine' (via the venues map when listed)."""
    head = re.sub(r",\s*\d{4}$", "", venue).split(",")[0]
    head = re.sub(r"\s+\d.*$", "", head).strip()
    if head.lower().startswith("arxiv"):
        return "arXiv"
    return venues.get(head.lower(), venues.get(venue.lower(), head))


def by_year(pubs: list[Publication]) -> list[tuple[int | str, list[Publication]]]:
    """Newest year first; within a year, newest publication date first."""
    groups: dict = defaultdict(list)
    for p in pubs:
        groups[p.year or "Undated"].append(p)
    order = sorted((y for y in groups if isinstance(y, int)), reverse=True) + (["Undated"] if "Undated" in groups else [])
    return [(y, sorted(sorted(groups[y], key=lambda p: p.title.lower()), key=date_key, reverse=True)) for y in order]


def date_key(p: Publication) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", p.date or "")][:3]
    return tuple(parts + [0] * (3 - len(parts)))
