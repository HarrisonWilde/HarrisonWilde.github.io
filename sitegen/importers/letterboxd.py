"""Letterboxd: Settings → Import & Export → Export your data (a .zip of CSVs).

One note per film. The first diary date becomes `date`, later ones `dates`;
liked films become favourites; reviews become the note's body.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import Note, csv_rows, export_files, html_to_markdown, norm

IGNORED_FOLDERS = {"deleted", "orphaned"}  # the export keeps removed entries here


def read(path: Path) -> list[Note]:
    files = export_files(path)

    def rows(name: str) -> list[dict]:
        matches = [k for k in files if (k == name or k.endswith("/" + name))
                   and not IGNORED_FOLDERS & set(k.split("/"))]
        return csv_rows(files[min(matches, key=lambda k: k.count("/"))]) if matches else []

    films: dict[tuple, dict] = {}

    def film(row: dict) -> dict:
        key = (row.get("Name", ""), row.get("Year", ""))
        return films.setdefault(key, {"uri": None, "rating": None, "watches": [], "tags": [], "reviews": [], "liked": False})

    for r in rows("watched.csv"):
        film(r)["uri"] = r.get("Letterboxd URI") or None
    for r in rows("ratings.csv"):
        if r.get("Rating"):
            film(r)["rating"] = float(r["Rating"])
    for r in rows("diary.csv"):
        f = film(r)
        if when := r.get("Watched Date") or r.get("Date"):
            f["watches"].append(date.fromisoformat(when))
        if r.get("Rating"):
            f["rating"] = float(r["Rating"])
        f["tags"] += [t.strip() for t in r.get("Tags", "").split(",") if t.strip()]
        f["uri"] = f["uri"] or r.get("Letterboxd URI")
    for r in rows("reviews.csv"):
        if r.get("Review"):
            film(r)["reviews"].append((r.get("Watched Date") or r.get("Date") or "", html_to_markdown(r["Review"])))
    for r in rows("likes/films.csv"):
        film(r)["liked"] = True

    notes = []
    for (name, year_text), f in films.items():
        if not name:
            continue
        year = int(year_text) if year_text.isdigit() else None
        watches = sorted(set(f["watches"]))
        fields = {
            "title": name,
            "year": year,
            "date": watches[0] if watches else None,
            "dates": watches[1:],
            "rating": f["rating"],
            "favourite": True if f["liked"] else None,
            "link": f["uri"],
            "tags": sorted(set(f["tags"])),
            "public": False,
        }
        reviews = sorted(f["reviews"])
        body = "\n\n".join(f"*{d}:* {text}" if len(reviews) > 1 and d else text for d, text in reviews)
        filename = f"{name} ({year})" if year else name
        notes.append(Note("films", filename, fields, body, key=("film", norm(name), str(year or ""))))
    return notes
