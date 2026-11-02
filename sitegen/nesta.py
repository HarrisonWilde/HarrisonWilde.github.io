"""Nesta articles you're credited on, read from your Nesta author page into data/nesta.json.

publications.py merges them into the research timeline alongside Scholar's papers.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .scholar import HEADERS, text

AUTHOR_PAGE = "https://www.nesta.org.uk/team/harry-wilde/"
ARTICLE = re.compile(r"^/(report|blog|feature|data-visualisation-and-interactive|toolkit|project-updates)/[^/]+/?$")
DELAY = 1.0  # seconds between requests


# ---------- parsing ----------


def parse_date(s: str) -> date | None:
    for fmt in ("%d.%m.%y", "%d.%m.%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_author_page(html: str) -> list[dict]:
    """Each listed article's title, link, kind ("Report", "Blog"…) and date."""
    soup = BeautifulSoup(html, "html.parser")
    articles: dict[str, dict] = {}
    for card in soup.select(".listing-item"):
        link = next((a["href"] for a in card.select("a[href]") if ARTICLE.match(urlparse(a["href"]).path)), None)
        if link is None:
            continue
        meta = [text(m) for m in card.select(".meta-item__label, .meta-item__description")]
        when = next((d for d in map(parse_date, meta) if d), None)
        articles.setdefault(urljoin(AUTHOR_PAGE, link), {
            "title": text(card.select_one(".listing-item__heading")),
            "link": urljoin(AUTHOR_PAGE, link),
            "kind": next((m for m in meta if m and not parse_date(m)), ""),
            "date": when.isoformat() if when else None,
        })
    return [a for a in articles.values() if a["title"]]


def parse_article(html: str) -> dict:
    """Authors, in page order, from an article's author block."""
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".page-heading__authors") or soup.select_one(".authors")
    names: list[str] = []
    for a in box.select('a[href*="/team/"]') if box else []:
        name = text(a)
        if name and name.lower() not in ("view profile", "our people") and name not in names:
            names.append(name)
    return {"authors": names}


# ---------- fetching ----------


def fetch(previous: list[dict]) -> list[dict]:
    known = {a["link"]: a for a in previous}
    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get(AUTHOR_PAGE, timeout=20)
    r.raise_for_status()
    articles = parse_author_page(r.text)
    for a in articles:
        if known.get(a["link"], {}).get("authors"):  # authors don't change; skip the request
            a["authors"] = known[a["link"]]["authors"]
            continue
        time.sleep(DELAY)
        try:
            page = session.get(a["link"], timeout=20)
            page.raise_for_status()
            a.update(parse_article(page.text))
        except requests.RequestException as exc:
            print(f"  couldn't fetch {a['link']} ({exc})")
            a["authors"] = []
    return articles


def main(root: Path) -> int:
    path = root / "data" / "nesta.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    print("Fetching your Nesta author page…")
    try:
        articles = fetch(old.get("articles", []))
    except requests.RequestException as exc:
        print(f"Couldn't reach Nesta ({exc}). Kept the existing data.")
        return 1
    if not articles and old.get("articles"):
        print("Nesta's page listed no articles; that looks wrong, so the existing data was kept.")
        return 1
    data = {"updated": date.today().isoformat(), "page": AUTHOR_PAGE, "articles": articles}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(articles)} Nesta articles to {path.relative_to(root)}")
    for a in articles:
        print(f"  {a['date']}  {a['title']}")
    return 0
