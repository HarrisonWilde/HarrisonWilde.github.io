"""Books from Goodreads (My Books → Import and export) or The StoryGraph (Manage account → Export).

The format is detected from the CSV header. Read dates, ratings and shelves
come across; Goodreads' private notes go inside %% %% so they stay private.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from . import Note, csv_rows, export_files, html_to_markdown, norm

GOODREADS_STATUS = {"read": "read", "currently-reading": "reading", "to-read": "want"}
STORYGRAPH_STATUS = {"read": "read", "currently-reading": "reading", "to-read": "want", "did-not-finish": "dnf"}
SERIES = re.compile(r"\s*\(([^()]*?),?\s*#(\d+(?:\.\d+)?)\)\s*$")


def read(path: Path) -> list[Note]:
    notes = []
    for name, text in export_files(path).items():
        if not name.lower().endswith(".csv"):
            continue
        rows = csv_rows(text)
        if not rows:
            continue
        if "Book Id" in rows[0] and "Exclusive Shelf" in rows[0]:
            notes += [goodreads(r) for r in rows]
        elif "Read Status" in rows[0]:
            notes += [storygraph(r) for r in rows]
    return [n for n in notes if n.fields.get("title")]


def goodreads(r: dict) -> Note:
    title, series = split_series(r.get("Title", ""))
    shelf = r.get("Exclusive Shelf", "")
    rating = int(r["My Rating"]) if r.get("My Rating", "0").isdigit() and int(r["My Rating"]) > 0 else None
    shelves = [s.strip() for s in r.get("Bookshelves", "").split(",") if s.strip() and s.strip() not in GOODREADS_STATUS]
    year = r.get("Original Publication Year") or r.get("Year Published")
    fields = {
        "title": title,
        "author": r.get("Author") or None,
        "year": int(year) if year and year.isdigit() else None,
        "series": series,
        "date": parse_date(r.get("Date Read")) if shelf == "read" else None,
        "rating": rating,
        "status": GOODREADS_STATUS.get(shelf, shelf or None),
        "isbn": clean_isbn(r.get("ISBN13") or r.get("ISBN")),
        "link": f"https://www.goodreads.com/book/show/{r['Book Id']}" if r.get("Book Id") else None,
        "tags": shelves,
        "public": False,
    }
    body = html_to_markdown(r.get("My Review", ""))
    if r.get("Private Notes"):
        body += f"\n\n%%\n{r['Private Notes'].strip()}\n%%"
    return Note("books", title, fields, body, key=("book", norm(title), norm(fields["author"])))


def storygraph(r: dict) -> Note:
    title, series = split_series(r.get("Title", ""))
    status = STORYGRAPH_STATUS.get(r.get("Read Status", ""), r.get("Read Status") or None)
    rating = r.get("Star Rating")
    author = (r.get("Authors") or "").split(",")[0].strip() or None
    tags = [t.strip() for t in (r.get("Tags") or "").split(",") if t.strip()]
    fields = {
        "title": title,
        "author": author,
        "series": series,
        "date": parse_date(r.get("Last Date Read")) if status in ("read", "dnf") else None,
        "rating": float(rating) if rating and re.fullmatch(r"\d+(\.\d+)?", rating) else None,
        "status": status,
        "isbn": clean_isbn(r.get("ISBN/UID")),
        "tags": tags,
        "public": False,
    }
    return Note("books", title, fields, html_to_markdown(r.get("Review", "")), key=("book", norm(title), norm(author)))


def split_series(title: str) -> tuple[str, str | None]:
    """'Leviathan Wakes (The Expanse, #1)' -> ('Leviathan Wakes', 'The Expanse #1')."""
    m = SERIES.search(title)
    if not m:
        return title.strip(), None
    return title[: m.start()].strip(), f"{m.group(1).strip()} #{m.group(2)}"


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def clean_isbn(text: str | None) -> str | None:
    digits = re.sub(r"[^0-9Xx]", "", text or "")
    return digits or None
