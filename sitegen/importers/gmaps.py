"""Places from Google Takeout: choose "Saved" (your lists) and "Maps (your places)".

- Each saved list becomes a tag; "Want to go" style lists set `status: want`,
  "Favourite places" style lists mark favourites.
- Starred places (Saved Places.json) keep their address and map link.
- Places you reviewed (Reviews.json) are `status: been`, with your rating and review.
The full address is a private field (see site.yaml), so it never reaches the public site.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import Note, csv_rows, export_files, norm

WANT_LISTS = {"want to go", "travel plans", "to visit", "to try"}
FAVOURITE_LISTS = {"favourite places", "favorite places", "favourites", "favorites"}
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")


def read(path: Path) -> list[Note]:
    places: dict[str, dict] = {}

    def place(title: str, url: str | None = None, address: str | None = None) -> dict:
        key = canonical_url(url) or f"{norm(title)}|{norm(address)}"
        p = places.setdefault(key, {"title": title, "url": url, "address": address, "tags": set(),
                                    "status": None, "favourite": False, "rating": None, "date": None, "notes": []})
        p["url"] = p["url"] or url
        p["address"] = p["address"] or address
        return p

    for name, text in export_files(path).items():
        parts = PurePosixPath(name).parts
        if name.lower().endswith(".csv") and "Saved" in parts:
            list_name = PurePosixPath(name).stem
            for r in csv_rows(text):
                title = r.get("Title")
                if not title:
                    continue
                p = place(title, r.get("URL") or None)
                apply_list(p, list_name)
                if note := (r.get("Note") or r.get("Comment")):
                    p["notes"].append(note)
        elif name.lower().endswith(".json"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
                continue
            reviews = PurePosixPath(name).stem.lower().startswith("review")
            for feature in data.get("features", []):
                props = lower_keys(feature.get("properties") or {})
                loc = lower_keys(props.get("location") or {})
                title = loc.get("name") or loc.get("business name") or props.get("title")
                if not title:
                    continue
                p = place(title, props.get("google_maps_url") or props.get("google maps url"), loc.get("address"))
                when = parse_time(props.get("date") or props.get("published"))
                if reviews:
                    p["status"] = "been"
                    p["rating"] = props.get("five_star_rating_published") or p["rating"]
                    p["date"] = when or p["date"]
                    if review := props.get("review_text_published"):
                        p["notes"].append(review)
                else:
                    p["tags"].add("starred")
                if comment := props.get("comment"):
                    p["notes"].append(comment)

    notes = []
    for p in merge_same_name(list(places.values())):
        city = city_from(p["address"])
        fields = {
            "title": p["title"],
            "type": None,
            "where": None,
            "city": city,
            "address": p["address"],
            "status": p["status"],
            "date": p["date"],
            "rating": p["rating"],
            "favourite": True if p["favourite"] else None,
            "map": p["url"],
            "tags": sorted(p["tags"]),
            "public": False,
        }
        body = "\n\n".join(dict.fromkeys(p["notes"]))
        notes.append(Note("places", p["title"], fields, body, key=("place", norm(p["title"]), norm(city))))
    return notes


def merge_same_name(places: list[dict]) -> list[dict]:
    """A saved-list entry (no address) and a starred or reviewed one (with address) are usually the same place.
    Same-named places with different addresses (two branches of a chain) stay separate."""
    groups: dict[str, list[dict]] = {}
    for p in places:
        groups.setdefault(norm(p["title"]), []).append(p)
    merged = []
    for group in groups.values():
        addresses = {norm(p["address"]) for p in group if p["address"]}
        if len(addresses) > 1:
            merged += group
            continue
        base = next((p for p in group if p["address"]), group[0])
        for p in group:
            if p is base:
                continue
            base["tags"] |= p["tags"]
            base["notes"] = p["notes"] + base["notes"]
            base["favourite"] = base["favourite"] or p["favourite"]
            base["rating"] = base["rating"] or p["rating"]
            base["date"] = base["date"] or p["date"]
            base["url"] = base["url"] or p["url"]
            if p["status"] == "been" or base["status"] is None:  # having been beats wanting to go
                base["status"] = p["status"]
        merged.append(base)
    return merged


def apply_list(p: dict, list_name: str) -> None:
    lowered = list_name.strip().lower()
    if lowered in WANT_LISTS:
        p["status"] = p["status"] or "want"
    elif lowered in FAVOURITE_LISTS:
        p["favourite"] = True
        p["status"] = "been"
    else:
        p["tags"].add(re.sub(r"\s+", "-", lowered))


def lower_keys(d: dict) -> dict:
    return {str(k).lower(): v for k, v in d.items()}


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"cid=(\d+)", url)
    return f"cid:{m.group(1)}" if m else url.split("?")[0].rstrip("/")


def parse_time(text) -> object:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def city_from(address: str | None) -> str | None:
    """'26 St John St, London EC1M 4AY, United Kingdom' -> 'London' (best effort)."""
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return None
    for candidate in reversed(parts[:-1]):
        cleaned = UK_POSTCODE.sub("", candidate)
        cleaned = " ".join(w for w in cleaned.split() if not any(ch.isdigit() for ch in w)).strip()
        if cleaned and not re.fullmatch(r"[A-Z]{2}", cleaned):  # skip US state codes
            return cleaned
    return None
