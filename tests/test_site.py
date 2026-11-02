"""Run with: uv run python -m unittest"""

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from sitegen import config
from sitegen.build import build, check_public
from sitegen.dates import parse_when
from sitegen.importers import books, gmaps, letterboxd, note_text
from sitegen.markup import strip_private

ROOT = config.ROOT
SAMPLE = ROOT / "examples" / "archive"
FIXTURES = ROOT / "tests" / "fixtures"


class AirGap(unittest.TestCase):
    """The public build must contain public entries only, with private parts removed."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cfg = config.load(archive=SAMPLE)
        cls.public = build(cfg, private=False, out=cls.tmp / "public")
        cls.private = build(cfg, private=True, out=cls.tmp / "private")
        cls.text = "\n".join(p.read_text() for p in (cls.tmp / "public").rglob("*") if p.suffix in {".html", ".xml"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_only_public_entries(self):
        self.assertTrue(all(e.public for e in self.public.entries))
        self.assertGreater(len(self.private.entries), len(self.public.entries))

    def test_private_entries_absent(self):
        for title in ("Caribou", "Piranesi", "Nighthawks", "Bar Leone", "On keeping records"):
            self.assertNotIn(title, self.text)
        self.assertFalse((self.tmp / "public" / "films" / "paris-texas-1984").exists())

    def test_no_scholar_or_orcid_links(self):
        for host in ("scholar.google", "orcid.org"):
            self.assertNotIn(host, self.text)

    def test_private_fields_and_comments_absent(self):
        for secret in ("A friend", "Two friends", "26 St John St", "Sample private note", "double percent", "%%"):
            self.assertNotIn(secret, self.text)

    def test_private_build_keeps_everything(self):
        page = (self.tmp / "private" / "films" / "past-lives-2023" / "index.html").read_text()
        self.assertIn("A friend", page)
        self.assertIn("private-note", page)

    def test_links_to_private_notes_become_text(self):
        post = (self.tmp / "public" / "writing" / "a-sample-post" / "index.html").read_text()
        self.assertIn('href="/films/past-lives-2023/"', post)
        self.assertNotIn("paris-texas", post)

    def test_check_public_catches_leaks(self):
        out = self.tmp / "leaky"
        out.mkdir()
        (out / "index.html").write_text("<p>%% secret %%</p>")
        with self.assertRaises(SystemExit):
            check_public(out, set())

    def test_private_reserved_fields_are_hidden(self):
        from dataclasses import replace

        from sitegen.entries import load_archive, publicize

        cfg = config.load(archive=SAMPLE)
        entries, _ = load_archive(cfg)
        films = [replace(e, collection=replace(e.collection, private=("rating", "link", "tags")))
                 for e in entries if e.collection.key == "films"]
        (past_lives,) = publicize(films)
        self.assertEqual((past_lives.rating, past_lives.link, past_lives.tags), (None, None, []))
        self.assertNotIn("rating", past_lives.fields)

    def test_archive_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            config.check_archive_location(ROOT / "archive")
        config.check_archive_location(SAMPLE)  # sample data is allowed


class Markup(unittest.TestCase):
    def test_strip_private(self):
        text = "Public.\n\n%%\nBlock secret\n%%\n\nInline %%secret%% here. %% unclosed"
        out = strip_private(text)
        self.assertNotIn("secret", out)
        self.assertNotIn("%%", out)
        self.assertIn("Public.", out)


class Scholar(unittest.TestCase):
    def test_parse_profile(self):
        from sitegen.scholar import parse_profile

        stats, rows = parse_profile((FIXTURES / "scholar" / "profile.html").read_text())
        self.assertEqual(stats, {"total_citations": 294, "h_index": 8, "i10_index": 8})
        first, second = rows
        self.assertEqual(first["title"], "Foundations of Bayesian learning from synthetic data")
        self.assertEqual((first["year"], first["citations"]), (2021, 57))
        self.assertTrue(first["detail_url"].startswith("https://scholar.google.com/citations?view_op=view_citation"))
        self.assertEqual(second["authors"], ["A Author", "B Author"])  # Scholar's "..." dropped
        self.assertEqual((second["year"], second["citations"], second["detail_url"]), (None, 0, None))

    def test_parse_details(self):
        from sitegen.scholar import parse_details

        d = parse_details((FIXTURES / "scholar" / "detail.html").read_text())
        self.assertEqual(d["authors"], ["Harrison Wilde", "Jack Jewson", "Sebastian Vollmer", "Chris Holmes"])
        self.assertEqual((d["date"], d["link"]), ("2021/3/18", "http://proceedings.mlr.press/v130/wilde21a.html"))
        self.assertEqual(d["journal"], "International conference on artificial intelligence and statistics")

    def test_publications_sorted_by_date_within_year(self):
        from sitegen.publications import Publication, by_year

        def pub(title, year, when):
            return Publication(title, [], year, "", "", None, None, when)

        groups = by_year([pub("B", 2021, "2021/1"), pub("A", 2021, "2021/8/30"), pub("C", 2023, "2023/7/5")])
        self.assertEqual([(y, [p.title for p in ps]) for y, ps in groups], [(2023, ["C"]), (2021, ["A", "B"])])


class Nesta(unittest.TestCase):
    def test_author_page(self):
        from sitegen.nesta import parse_author_page

        articles = parse_author_page((FIXTURES / "nesta" / "author.html").read_text())
        self.assertEqual([a["date"] for a in articles], ["2026-07-09", "2026-03-03"])  # nav links ignored
        self.assertEqual(articles[0]["kind"], "Report")
        self.assertTrue(articles[1]["link"].startswith("https://www.nesta.org.uk/report/modelling"))

    def test_article_authors(self):
        from sitegen.nesta import parse_article

        self.assertEqual(parse_article((FIXTURES / "nesta" / "article.html").read_text())["authors"],
                         ["Shyamolie Biyani", "Harry Wilde"])

    def test_merged_into_publications(self):
        import json

        from sitegen.publications import by_year, load

        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "data").mkdir()
            (tmp / "data" / "publications.json").write_text(json.dumps({"publications": [
                {"title": "Modelling the impact of a tax on unhealthy foods", "authors": ["H Wilde"], "year": 2026,
                 "link": "https://scholar.google.com/scholar?cluster=1"}]}))
            (tmp / "data" / "nesta.json").write_text(json.dumps({"page": "https://www.nesta.org.uk/team/harry-wilde/", "articles": [
                {"title": "Modelling the impact of a tax on unhealthy foods", "authors": [], "kind": "Report", "date": "2026-03-03"},
                {"title": "The healthy food standard", "authors": ["A Colleague", "B Colleague", "Harrison Wilde"], "kind": "Report", "date": "2026-07-09"}]}))
            pubs, _ = load(tmp)
            self.assertEqual(len(pubs), 2)  # the article Scholar already lists isn't repeated
            nesta = next(p for p in pubs if p.title == "The healthy food standard")
            self.assertEqual((nesta.year, nesta.venue), (2026, "Nesta report"))
            self.assertEqual(nesta.authors, ["Harrison Wilde", "A Colleague", "B Colleague"])  # me first, rest unchanged
            self.assertEqual(by_year(pubs)[0][1][0].title, "The healthy food standard")
            self.assertIsNone(next(p for p in pubs if p.title.startswith("Modelling")).link)  # no links to Scholar
        finally:
            shutil.rmtree(tmp)


class Images(unittest.TestCase):
    def test_public_images_resized_stripped_and_private_ones_left_out(self):
        from PIL import Image

        tmp = Path(tempfile.mkdtemp())
        try:
            archive = tmp / "archive"
            (archive / "art").mkdir(parents=True)
            (archive / "attachments").mkdir()
            exif = Image.Exif()
            exif[0x0110] = "iPhone"  # camera model; GPS would sit alongside
            Image.new("RGB", (3000, 2000), "white").save(archive / "attachments" / "photo.jpg", exif=exif)
            Image.new("RGB", (100, 100), "black").save(archive / "attachments" / "secret.jpg")
            (archive / "art" / "Public.md").write_text(
                "---\ntitle: Public\npublic: true\nimage: photo.jpg\ncaption: My photo\n---\nWords.\n\n%%\n![[secret.jpg]]\n%%\n")
            (archive / "art" / "Private.md").write_text("---\ntitle: Private\nimage: secret.jpg\n---\n")
            build(config.load(archive=archive), private=False, out=tmp / "site")
            media = tmp / "site" / "media"
            self.assertEqual(sorted(p.name for p in media.iterdir()), ["photo.jpg"])
            with Image.open(media / "photo.jpg") as im:
                self.assertEqual(max(im.size), 1600)
                self.assertEqual(len(im.getexif()), 0)
            page = (tmp / "site" / "art" / "public" / "index.html").read_text()
            self.assertIn('src="/media/photo.jpg"', page)
            self.assertIn("<figcaption>My photo</figcaption>", page)
        finally:
            shutil.rmtree(tmp)


class Deploy(unittest.TestCase):
    def test_uploads_what_cloudflare_asks_for_then_switches_the_worker(self):
        import base64
        import json
        from unittest.mock import patch

        from sitegen import deploy

        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / ".hw-build").touch()
            (tmp / "index.html").write_text("<p>home</p>")
            (tmp / "style.css").write_text("p {}")
            files = deploy.manifest(tmp)
            self.assertEqual(sorted(files), ["/index.html", "/style.css"])  # the build marker stays behind
            page = files["/index.html"]["hash"]
            replies = [{"jwt": "upload", "buckets": [[page]]}, {"jwt": "done"}, {}, {}, {}]
            with patch.object(deploy, "read_token", return_value="token"), \
                    patch.object(deploy, "call", side_effect=replies) as call:
                deploy.publish(tmp, "account", "site", ["example.page"])
            _, url, token = call.call_args_list[1].args
            _, content, kind = call.call_args_list[1].kwargs["files"][page]
            self.assertEqual((token, base64.b64decode(content), kind), ("upload", b"<p>home</p>", "text/html; charset=utf-8"))
            metadata = json.loads(call.call_args_list[2].kwargs["files"]["metadata"][1])
            self.assertEqual(metadata["assets"]["jwt"], "done")
            self.assertEqual(metadata["assets"]["config"]["not_found_handling"], "none")
            self.assertFalse(call.call_args_list[3].kwargs["json"]["enabled"])  # no workers.dev copy
            self.assertEqual(call.call_args_list[4].kwargs["json"], {"hostname": "example.page", "service": "site"})
        finally:
            shutil.rmtree(tmp)

    def test_refuses_partial_builds(self):
        from types import SimpleNamespace

        from sitegen.deploy import check_ready

        ready = {"account": "a", "worker": "w", "domains": ["example.page"]}
        clean, warned = SimpleNamespace(warnings=[]), SimpleNamespace(warnings=["Archive not found"])
        real = SimpleNamespace(archive=Path("/somewhere/else"), cloudflare=ready)
        check_ready(real, clean)
        with self.assertRaises(SystemExit):
            check_ready(real, warned)
        with self.assertRaises(SystemExit):
            check_ready(SimpleNamespace(archive=SAMPLE, cloudflare=ready), clean)
        with self.assertRaises(SystemExit):
            check_ready(SimpleNamespace(archive=Path("/somewhere/else"), cloudflare={}), clean)


class PrivateServer(unittest.TestCase):
    def test_only_loopback_and_tunnel_answered(self):
        from sitegen.serve import allowed_server

        verify = allowed_server(["100.111.254.0/24"]).verify_request
        self.assertTrue(verify(None, None, ("127.0.0.1", 50000)))
        self.assertTrue(verify(None, None, ("100.111.254.2", 50000)))
        self.assertFalse(verify(None, None, ("192.168.1.20", 50000)))  # someone else on the Wi-Fi


class Dates(unittest.TestCase):
    def test_partial(self):
        self.assertEqual(parse_when(2019).long, "2019")
        self.assertEqual(parse_when("2019-05").long, "May 2019")
        self.assertEqual(parse_when(date(2026, 10, 12)).short, "12 Oct")
        self.assertIsNone(parse_when(None))
        with self.assertRaises(ValueError):
            parse_when("last summer")


class Importers(unittest.TestCase):
    def test_letterboxd(self):
        films = {n.fields["title"]: n.fields | {"body": n.body} for n in letterboxd.read(FIXTURES / "letterboxd")}
        self.assertEqual(set(films), {"Past Lives", "Paris, Texas", "Heat"})  # deleted/ is ignored
        self.assertEqual(films["Past Lives"]["date"], date(2026, 10, 12))
        self.assertEqual(films["Past Lives"]["body"], "So *good*.\nReally.")
        self.assertEqual(films["Paris, Texas"]["date"], date(2024, 1, 30))
        self.assertEqual(films["Paris, Texas"]["dates"], [date(2026, 6, 3)])
        self.assertTrue(films["Paris, Texas"]["favourite"])
        self.assertEqual(films["Heat"]["rating"], 4.0)
        self.assertIsNone(films["Heat"]["date"])
        self.assertTrue(all(f["public"] is False for f in films.values()))

    def test_goodreads(self):
        notes = {n.fields["title"]: n for n in books.read(FIXTURES / "goodreads_library_export.csv")}
        d = notes["The Dispossessed"]
        self.assertEqual((d.fields["date"], d.fields["rating"], d.fields["status"]), (date(2026, 8, 30), 5, "read"))
        self.assertEqual(d.fields["isbn"], "9780061054884")
        self.assertIn("%%\nBorrowed from a friend\n%%", d.body)
        lw = notes["Leviathan Wakes"]
        self.assertEqual((lw.fields["series"], lw.fields["status"], lw.fields["rating"]), ("The Expanse #1", "want", None))

    def test_storygraph(self):
        (n,) = books.read(FIXTURES / "storygraph.csv")
        self.assertEqual((n.fields["title"], n.fields["rating"], n.fields["date"]), ("Piranesi", 4.75, date(2026, 1, 20)))

    def test_google_maps(self):
        places = {n.fields["title"]: n for n in gmaps.read(FIXTURES / "takeout")}
        self.assertEqual(set(places), {"St. JOHN", "Bar Leone"})  # list, starred and review entries merged
        sj = places["St. JOHN"].fields
        self.assertEqual((sj["status"], sj["city"], sj["rating"], sj["favourite"]), ("been", "London", 5, True))
        self.assertEqual(sj["date"], date(2024, 3, 10))
        self.assertIn("Still the best.", places["St. JOHN"].body)
        self.assertEqual(places["Bar Leone"].fields["status"], "want")

    def test_note_round_trip(self):
        from sitegen.entries import read_note

        tmp = Path(tempfile.mkdtemp())
        try:
            (n,) = books.read(FIXTURES / "storygraph.csv")
            path = tmp / "Piranesi.md"
            path.write_text(note_text(n.fields, n.body))
            fields, body = read_note(path)
            self.assertEqual(fields["date"], date(2026, 1, 20))
            self.assertIs(fields["public"], False)
            self.assertEqual(body.strip(), "Strange and lovely.")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
