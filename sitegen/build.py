"""Build the public site (_site/) or the private one (_private/) from the same templates."""

from __future__ import annotations

import hashlib
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup
from PIL import Image, ImageOps

from . import publications
from .config import ROOT, Config
from .entries import Entry, load_archive, publicize, read_note, stars
from .markup import Renderer, is_image

OUTPUT = {False: ROOT / "_site", True: ROOT / "_private"}
MARKER = ".hw-build"  # only directories carrying this marker are ever deleted
MEDIA_SKIP = {".obsidian", ".trash", ".git"}


@dataclass
class Result:
    out: Path
    private: bool
    entries: list[Entry]
    left_out: int  # entries in the archive that this build doesn't show
    warnings: list[str] = field(default_factory=list)


def build(cfg: Config, private: bool = False, out: Path | None = None) -> Result:
    out = out or OUTPUT[private]
    everything, warnings = load_archive(cfg)
    entries = everything if private else publicize(everything)
    private_urls = {e.url for e in everything if not e.public}
    left_out = len(everything) - len(entries)
    del everything  # from here on the public build only has sanitised copies
    warnings += icloud_placeholders(cfg)

    staging = out.with_name(out.name + ".tmp")
    reset_dir(staging)
    site = Site(cfg, private, entries, staging, warnings)
    site.render_all()
    copy_static(staging)
    if not private:
        check_public(staging, private_urls)
    reset_dir(out, create=False)
    staging.rename(out)
    return Result(out, private, entries, left_out, warnings)


class Site:
    def __init__(self, cfg: Config, private: bool, entries: list[Entry], out: Path, warnings: list[str]):
        self.cfg, self.private, self.out, self.warnings = cfg, private, out, warnings
        self.entries = sorted(entries, key=lambda e: e.sort_key, reverse=True)
        self.by_collection: dict[str, list[Entry]] = defaultdict(list)
        for e in self.entries:
            self.by_collection[e.collection.key].append(e)
        self.feed = [e for e in self.entries if e.in_feed]
        self.notes: dict[str, str] = {}
        for e in self.entries:
            self.notes.setdefault(e.stem.lower(), e.url)
            self.notes.setdefault(e.title.lower(), e.url)
        self._media_index: dict[str, Path] | None = None
        self.note_url = lambda name: self.notes.get(name.strip().lower())
        self.today = date.today()
        self.pubs, self.pub_meta = publications.load(ROOT)
        self.env = self.make_env()

    # ---------- rendering ----------

    def make_env(self) -> Environment:
        env = Environment(
            loader=FileSystemLoader(ROOT / "templates"),
            autoescape=select_autoescape(["html", "xml"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        plain = Renderer(self.private, self.note_url, lambda name: None)
        env.filters.update(
            stars=stars,
            label=lambda s: s.replace("_", " "),
            inline=lambda s: Markup(plain.inline(s)),
            host=lambda u: urlparse(u).netloc.removeprefix("www.") or u,
            autolink=autolink,
        )
        nav = [("about", "/")]
        if self.pubs:
            nav.append(("research", "/research/"))
        if self.feed:
            nav.append(("feed", "/feed/"))
        if self.private:
            nav.append(("library", "/library/"))
        env.globals.update(
            site=self.cfg,
            private=self.private,
            nav=nav,
            today=self.today,
            has_feed=bool(self.feed),
            private_count=sum(1 for e in self.entries if not e.public),
            css_version=hashlib.sha1((ROOT / "static" / "style.css").read_bytes()).hexdigest()[:8],
            total_count=len(self.entries),
        )
        return env

    def page(self, path: str, template: str, current: str = "", **context) -> None:
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        context.setdefault("body_class", "")
        html = self.env.get_template(template).render(current=current, **context)
        target.write_text(html, encoding="utf-8")

    def render_all(self) -> None:
        for e in self.entries:
            self.prepare(e)
        self.render_home()
        if self.pubs:
            self.render_research()
        if self.feed:
            self.render_feed()
        for key, items in self.by_collection.items():
            self.render_collection(self.cfg.collections[key], items)
            for e in items:
                template = "post.html" if key == "writing" else "entry.html"
                self.page(f"{key}/{e.slug}/index.html", template, current=f"/{key}/", e=e, c=e.collection)
        if self.private:
            self.render_dashboard()

    def prepare(self, e: Entry) -> None:
        """Attach the rendered body and image URL (public entries arrive here already sanitised)."""
        render = Renderer(self.private, self.note_url, self.media)
        e.html = Markup(render(e.body)) if e.body.strip() else ""
        e.image_url = self.image_url(e.image) if e.image else None
        e.source_rel = str(e.source.relative_to(self.cfg.archive)) if self.cfg.archive else e.source.name

    def render_home(self) -> None:
        _, bio = read_note(ROOT / "content" / "home.md")
        plain = Renderer(self.private, self.note_url, lambda name: None)
        self.page("index.html", "home.html", current="/", bio=Markup(plain(bio)), recent=group_by_year(self.feed[:6]))

    def render_research(self) -> None:
        self.page(
            "research/index.html",
            "research.html",
            current="/research/",
            pubs=publications.by_year(self.pubs),
            me=self.pub_meta["me"],
        )

    def filters(self, current: str) -> list[dict]:
        keys = [k for k in self.cfg.collections if any(e.collection.key == k for e in self.feed)]
        links = [{"label": "all", "href": "/feed/", "current": current == "/feed/"}]
        links += [
            {"label": self.cfg.collections[k].label.lower(), "href": f"/{k}/", "current": current == f"/{k}/"}
            for k in keys
        ]
        # A collection page has no heading, so it always shows which filter it is.
        return links if len(keys) > 1 or current != "/feed/" else []

    def render_feed(self) -> None:
        self.page(
            "feed/index.html",
            "feed.html",
            current="/feed/",
            heading="Feed",
            filters=self.filters("/feed/"),
            groups=group_by_year(self.feed),
            show_kind=True,
        )
        updated = max((e.when.day for e in self.feed), default=self.today)
        if not self.private:
            self.page("feed.xml", "feed.xml", items=self.feed[:50], updated=atom_time(updated))

    def render_collection(self, c, items: list[Entry]) -> None:
        path, current = f"{c.key}/index.html", f"/{c.key}/"
        if c.key == "writing":
            self.page(path, "writing.html", current=current, c=c, entries=items)
        elif self.private:
            self.page(path, "library.html", current="/library/", c=c, entries=items,
                      public_count=sum(1 for e in items if e.public))
        else:
            dated = [e for e in items if e.when]
            undated = [e for e in items if not e.when]
            self.page(path, "feed.html", current="/feed/", heading=c.label,
                      filters=self.filters(current), groups=group_by_year(dated) + ([("Undated", undated)] if undated else []),
                      show_kind=False)

    def render_dashboard(self) -> None:
        counts = []
        for key, c in self.cfg.collections.items():
            items = self.by_collection.get(key, [])
            counts.append((c, len(items), sum(1 for e in items if e.public)))
        on_this_day = [
            e for e in self.entries
            if e.when and e.when.precision == "day" and e.when.day.year < self.today.year
            and (e.when.day.month, e.when.day.day) == (self.today.month, self.today.day)
        ]
        statuses = Counter(e.status for e in self.entries if e.status)
        self.page(
            "library/index.html",
            "dashboard.html",
            current="/library/",
            counts=counts,
            on_this_day=on_this_day,
            latest=group_by_year([e for e in self.entries if e.when][:12]),
            undated=sum(1 for e in self.entries if not e.when),
            statuses=sorted(statuses.items()),
            warnings=self.warnings,
        )

    # ---------- media ----------

    def media_index(self) -> dict[str, Path]:
        if self._media_index is None:
            self._media_index = {}
            if self.cfg.archive and self.cfg.archive.is_dir():
                for p in self.cfg.archive.rglob("*"):
                    rel = p.relative_to(self.cfg.archive).parts
                    if p.is_file() and is_image(p.name) and not (set(rel) & MEDIA_SKIP):
                        self._media_index.setdefault(p.name.lower(), p)
        return self._media_index

    def media(self, name: str) -> str | None:
        src = self.media_index().get(Path(name).name.lower())
        if src is None:
            self.warnings.append(f"Image not found in the archive: {name}")
            return None
        dest = self.out / "media" / src.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if self.private or src.suffix.lower() in {".gif", ".svg"}:
                shutil.copy2(src, dest)
            elif not publish_image(src, dest):
                self.warnings.append(f"Couldn't process {src.name} for the public site, so it was left out.")
                return None
        return "/media/" + quote(src.name)

    def image_url(self, ref: str) -> str | None:
        if ref.startswith(("http://", "https://")):
            return ref
        return self.media(ref.removeprefix("![[").removeprefix("[[").removesuffix("]]"))


# ---------- helpers ----------


def group_by_year(entries: list[Entry]) -> list[tuple[int, list[Entry]]]:
    groups: list[tuple[int, list[Entry]]] = []
    for e in entries:
        year = e.when.day.year
        if not groups or groups[-1][0] != year:
            groups.append((year, []))
        groups[-1][1].append(e)
    return groups


def publish_image(src: Path, dest: Path, longest: int = 1600) -> bool:
    """Resize for the web and drop all metadata (phone photos carry GPS) before an image goes public."""
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)  # bake in the camera's rotation before the EXIF goes
            im.thumbnail((longest, longest))
            if dest.suffix.lower() in {".jpg", ".jpeg"}:
                im.convert("RGB").save(dest, quality=82, optimize=True, progressive=True)
            else:
                im.save(dest, optimize=True)
        return True
    except Exception:
        dest.unlink(missing_ok=True)
        return False


def atom_time(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def autolink(value: str) -> Markup:
    if value.startswith(("http://", "https://")):
        host = urlparse(value).netloc.removeprefix("www.")
        return Markup('<a href="{0}">{1}</a>').format(value, host)
    return Markup.escape(value)


def reset_dir(path: Path, create: bool = True) -> None:
    if path.exists():
        if not (path / MARKER).exists() and any(path.iterdir()):
            raise SystemExit(f"Refusing to delete {path}: it wasn't created by this build.")
        shutil.rmtree(path)
    if create:
        path.mkdir(parents=True)
        (path / MARKER).touch()


def copy_static(out: Path) -> None:
    for src in (ROOT / "static").rglob("*"):
        if src.is_file():
            dest = out / src.relative_to(ROOT / "static")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def icloud_placeholders(cfg: Config) -> list[str]:
    """iCloud can evict files to save space, leaving '.Name.md.icloud' stubs the build can't read."""
    if not cfg.archive or not cfg.archive.is_dir():
        return []
    stubs = [p for p in cfg.archive.rglob(".*.icloud") if not (set(p.relative_to(cfg.archive).parts) & MEDIA_SKIP)]
    if not stubs:
        return []
    return [f"{len(stubs)} file(s) in the archive aren't downloaded from iCloud and were skipped "
            "(Finder: right-click the vault folder → Keep Downloaded)."]


def check_public(out: Path, private_urls: set[str]) -> None:
    """Last line of defence: fail the public build if anything private reached the output."""
    problems = []
    for url in private_urls:
        if (out / url.strip("/") / "index.html").exists():
            problems.append(f"page for a private entry: {url}")
    for path in out.rglob("*"):
        if path.suffix not in {".html", ".xml"}:
            continue
        text = path.read_text(encoding="utf-8")
        for needle, why in (("%%", "an Obsidian private comment"), ("private-note", "a private note"),
                            ("private-bar", "the private-build banner")):
            if needle in text:
                problems.append(f"{why} in {path.relative_to(out)}")
    if problems:
        shutil.rmtree(out)
        raise SystemExit("Public build stopped: private content would have been published.\n  " + "\n  ".join(problems))
