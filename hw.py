"""wilde.page: one command for everything.

  uv run hw.py serve                     public site at http://localhost:4000, rebuilt on change
  uv run hw.py serve --private           your whole archive at http://localhost:4001
  uv run hw.py build [--private] [--list]
  uv run hw.py deploy                    build the public site and publish it to wilde.page
  uv run hw.py publications              refresh publications from Google Scholar and Nesta
  uv run hw.py vault init PATH           set up an Obsidian vault for the archive
  uv run hw.py service install           keep the private site running (Mac + WireGuard) at login
  uv run hw.py schedule install          publish every hour if anything has changed

Add --archive PATH to any command to use a different archive, e.g. examples/archive.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from sitegen import config


def cmd_build(args) -> None:
    from sitegen.build import build

    cfg = config.load(archive=args.archive)
    result = build(cfg, private=args.private)
    report(cfg, result, args.list)


def cmd_serve(args) -> None:
    from sitegen.build import build
    from sitegen.serve import serve

    def rebuild() -> Path:
        return build(config.load(archive=args.archive), private=args.private).out

    cfg = config.load(archive=args.archive)
    report(cfg, build(cfg, private=args.private), False)
    settings = cfg.private_server if args.private else {}
    serve(
        rebuild,
        cfg.archive,
        port=args.port or settings.get("port") or (4001 if args.private else 4000),
        hosts=args.host or settings.get("hosts") or ["127.0.0.1"],
        allow=settings.get("allow") or [],
        strict=args.strict,
    )


def cmd_deploy(args) -> None:
    from sitegen import deploy
    from sitegen.build import build

    if args.if_changed and deploy.uncommitted_changes():
        print(f"{datetime.now():%Y-%m-%d %H:%M} skipped: the site's code has uncommitted changes")
        return
    cfg = config.load()
    with tempfile.TemporaryDirectory() as tmp:  # its own copy, so a running preview can't interfere
        result = build(cfg, out=Path(tmp) / "site")
        if args.if_changed and not result.warnings and not deploy.changed(result.out):
            return
        report(cfg, result, True)
        deploy.check_ready(cfg, result)
        if not args.yes and input(f"Publish this to {cfg.url}? [y/N] ").strip().lower() != "y":
            print("Nothing published.")
            return
        deploy.publish(result.out, cfg.cloudflare["account"], cfg.cloudflare["worker"], cfg.cloudflare["domains"])
    print(f"{datetime.now():%Y-%m-%d %H:%M} published to {cfg.url}")


def report(cfg, result, list_entries: bool) -> None:
    for w in result.warnings:
        print(f"warning: {w}")
    counts = Counter(e.collection.key for e in result.entries)
    summary = ", ".join(f"{k} {n}" for k, n in counts.items()) or "none"
    if result.private:
        print(f"private build → {result.out.name}/  {len(result.entries)} {"entry" if len(result.entries) == 1 else "entries"} ({summary})")
    else:
        print(f"public build → {result.out.name}/  {len(result.entries)} public entries ({summary}); "
              f"{result.left_out} private entries left out")
        if config.is_sample(cfg.archive):
            print("note: built from the sample archive; don't publish this")
    if list_entries:
        for e in sorted(result.entries, key=lambda e: (e.collection.key, e.sort_key)):
            flag = "" if e.public else "  (private)"
            print(f"  {e.collection.kind:8} {e.when.iso if e.when else '—':10}  {e.title}{flag}")


def cmd_publications(args) -> None:
    from sitegen import nesta, scholar

    sources = {"scholar": scholar.main, "nesta": nesta.main}
    failures = [name for name, run in sources.items() if args.source in (name, "all") and run(config.ROOT) != 0]
    sys.exit(1 if failures else 0)


def cmd_service(args) -> None:
    from sitegen import service

    agent = "publish" if args.command == "schedule" else "private"
    service.install(agent) if args.action == "install" else service.uninstall(agent)


def cmd_vault(args) -> None:
    from sitegen.vault import init_vault

    init_vault(Path(args.path).expanduser())


def main() -> None:
    parser = argparse.ArgumentParser(prog="hw.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="build the site once")
    p.add_argument("--private", action="store_true", help="include everything (output in _private/)")
    p.add_argument("--list", action="store_true", help="list the entries in this build")
    p.add_argument("--archive", help="archive folder (default: site.yaml)")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("serve", help="build, serve locally and rebuild on change")
    p.add_argument("--private", action="store_true", help="serve the private build")
    p.add_argument("--port", type=int)
    p.add_argument("--host", action="append", help="address to listen on (repeatable; default: site.yaml)")
    p.add_argument("--strict", action="store_true", help="exit unless every address is available")
    p.add_argument("--archive", help="archive folder (default: site.yaml)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("deploy", help="build the public site and publish it")
    p.add_argument("--yes", action="store_true", help="don't ask before publishing")
    p.add_argument("--if-changed", action="store_true", help="do nothing if the site hasn't changed since the last publish")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("publications", aliases=["scholar"], help="refresh publications from Google Scholar and Nesta")
    p.add_argument("source", nargs="?", choices=["all", "scholar", "nesta"], default="all")
    p.set_defaults(func=cmd_publications)

    p = sub.add_parser("service", help="run the private site in the background at login (launchd)")
    p.add_argument("action", choices=["install", "uninstall"])
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("schedule", help="publish every hour if anything has changed (launchd)")
    p.add_argument("action", choices=["install", "uninstall"])
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("vault", help="set up the Obsidian vault")
    p.add_argument("action", choices=["init"])
    p.add_argument("path", help="vault folder")
    p.set_defaults(func=cmd_vault)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
