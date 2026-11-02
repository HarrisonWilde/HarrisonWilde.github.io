"""Refresh data/publications.json from a Google Scholar profile.

Scholar has no API and rate-limits scrapers, so this runs by hand and slowly.
Parsing is kept in pure functions (tested against fixture HTML); fetching is a
short loop around them. A blocked or partial run never replaces good data:
details it can't fetch this time are carried over from the previous run.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

USER = "nkElOLUAAAAJ"
BASE = "https://scholar.google.com"
PROFILE = f"{BASE}/citations?user={USER}&hl=en"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}
DELAY = 2.0  # seconds between requests
# Detail-page field labels we keep, and the key each is stored under.
DETAIL_FIELDS = {
    "authors": "authors", "inventors": "authors", "publication date": "date",
    "journal": "journal", "conference": "journal", "book": "journal", "source": "journal",
}
CARRIED_OVER = ("authors", "link", "journal", "date")


class Blocked(Exception):
    """Scholar is asking for a captcha."""


# ---------- parsing ----------


def text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def number(s: str) -> int | None:
    digits = re.sub(r"\D", "", s)
    return int(digits) if digits else None


def names(s: str) -> list[str]:
    return [n.strip() for n in s.split(",") if n.strip() not in ("", "...", "…")]


def parse_profile(html: str) -> tuple[dict, list[dict]]:
    """Citation stats and one dict per publication row. Each row keeps a `detail_url` (or None)."""
    soup = BeautifulSoup(html, "html.parser")
    cells = [number(text(td)) for td in soup.select("td.gsc_rsb_std")]
    stats = dict(zip(("total_citations", "h_index", "i10_index"), cells[0:6:2])) if len(cells) >= 6 else {}
    return stats, [row for tr in soup.select("tr.gsc_a_tr") if (row := parse_row(tr))]


def parse_row(tr: Tag) -> dict | None:
    a = tr.select_one("a.gsc_a_at")
    if a is None:
        return None
    gray = [text(div) for div in tr.select("div.gs_gray")]
    href = a.get("data-href") or a.get("href") or ""
    return {
        "title": text(a),
        "authors": names(gray[0]) if gray else [],  # truncated by Scholar; the detail page has them all
        "year": number(text(tr.select_one("td.gsc_a_y"))),
        "venue": gray[1] if len(gray) > 1 else "",
        "citations": number(text(tr.select_one("a.gsc_a_ac"))) or 0,
        "detail_url": BASE + href if href.startswith("/") else None,
    }


def parse_details(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict = {}
    link = soup.select_one("a.gsc_oci_title_link")
    if link is not None and link.get("href"):
        out["link"] = link["href"]
    for row in soup.select("div.gs_scl"):
        key = DETAIL_FIELDS.get(text(row.select_one("div.gsc_oci_field")).lower())
        value = text(row.select_one("div.gsc_oci_value"))
        if key and value and key not in out:
            out[key] = names(value) if key == "authors" else value
    return out


# ---------- fetching ----------


def fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=20)
    if r.status_code == 429 or "gs_captcha" in r.text or "unusual traffic" in r.text.lower():
        raise Blocked
    r.raise_for_status()
    return r.text


def scrape(previous: dict) -> dict:
    earlier = {p["title"].lower(): p for p in previous.get("publications", [])}
    session = requests.Session()
    session.headers.update(HEADERS)
    stats, rows = parse_profile(fetch(session, PROFILE + "&cstart=0&pagesize=100&sortby=pubdate"))
    pubs, blocked = [], False
    for i, row in enumerate(rows, 1):
        url = row.pop("detail_url")
        print(f"  [{i}/{len(rows)}] {row['title'][:72]}")
        details = {}
        if url and not blocked:
            time.sleep(DELAY)
            try:
                details = parse_details(fetch(session, url))
            except Blocked:
                blocked = True
                print("  Scholar started asking for a captcha; reusing earlier details for the rest.")
            except requests.RequestException as exc:
                print(f"  couldn't fetch details ({exc}); reusing earlier ones")
        if not details:
            old = earlier.get(row["title"].lower(), {})
            details = {k: old[k] for k in CARRIED_OVER if old.get(k)}
        pubs.append(row | details)
    return {"updated": date.today().isoformat(), "profile": PROFILE, "stats": stats, "publications": pubs}


def main(root: Path) -> int:
    path = root / "data" / "publications.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    print("Fetching your Google Scholar profile (slowly, to stay polite)…")
    try:
        new = scrape(old)
    except Blocked:
        print("Google Scholar is asking for a captcha from this connection. Kept the existing data; try again later.")
        return 1
    except requests.RequestException as exc:
        print(f"Couldn't reach Google Scholar ({exc}). Kept the existing data.")
        return 1
    had, got = len(old.get("publications", [])), len(new["publications"])
    if got == 0 or got < had * 0.8:
        print(f"Scholar returned {got} publications (had {had}); that looks wrong, so the existing data was kept.")
        return 1
    path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {got} publications to {path.relative_to(root)}; stats: {new['stats']}")
    before = {p["title"] for p in old.get("publications", [])}
    after = {p["title"] for p in new["publications"]}
    for title in sorted(after - before):
        print(f"  new: {title}")
    for title in sorted(before - after):
        print(f"  gone: {title}")
    return 0
