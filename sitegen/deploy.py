"""Publish the public build to Cloudflare from this Mac (the archive is in iCloud, so nothing else can build it).

Uses Cloudflare's upload API for static files: send a list of file hashes, upload the files it asks for, then
switch the Worker to them. Each publish replaces the whole site, and no earlier version stays online.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import subprocess
from pathlib import Path

import requests

from . import config
from .build import MARKER

API = "https://api.cloudflare.com/client/v4"
KEYCHAIN_SERVICE = "wilde-page-cloudflare"
COMPATIBILITY_DATE = "2026-11-02"
ASSET_CONFIG = {"html_handling": "auto-trailing-slash", "not_found_handling": "none"}


def check_ready(cfg, result) -> None:
    """Never replace the live site with a partial build: a missing archive or an offloaded note would drop entries."""
    if config.is_sample(cfg.archive):
        raise SystemExit("Not publishing: this was built from the sample archive.")
    if result.warnings:
        raise SystemExit("Not publishing until the warnings above are fixed.")
    if not all(cfg.cloudflare.get(key) for key in ("account", "worker", "domains")):
        raise SystemExit("Not publishing: site.yaml needs cloudflare: account, worker and domains.")


def manifest(site: Path) -> dict[str, dict]:
    """Every file's path, hash and size."""
    files = {}
    for path in sorted(p for p in site.rglob("*") if p.is_file() and p.name != MARKER):
        data = path.read_bytes()
        digest = hashlib.sha256(base64.b64encode(data) + path.suffix.lstrip(".").encode()).hexdigest()[:32]
        files["/" + path.relative_to(site).as_posix()] = {"hash": digest, "size": len(data)}
    return files


def content_type(path: str) -> str:
    """Cloudflare serves each file with the type it was uploaded with."""
    if path.endswith(".xml"):
        return "application/atom+xml"  # the feed
    kind = mimetypes.guess_type(path, strict=False)[0] or "application/octet-stream"
    return f"{kind}; charset=utf-8" if kind.startswith("text/") else kind


def read_token() -> str:
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    if found.returncode != 0:
        raise SystemExit("No Cloudflare token in the Keychain. Save one with:\n"
                         f"  security add-generic-password -U -s {KEYCHAIN_SERVICE} -a deploy -w")
    return found.stdout.strip()


def call(method: str, url: str, token: str, **kwargs) -> dict:
    response = requests.request(method, url, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kwargs)
    body = response.json() if "json" in response.headers.get("content-type", "") else {}
    if not response.ok or not body.get("success"):
        raise SystemExit(f"Cloudflare refused {method} {url}: {body.get('errors') or response.status_code}")
    return body.get("result") or {}


def publish(site: Path, account: str, worker: str, domains: list[str]) -> None:
    token, base = read_token(), f"{API}/accounts/{account}/workers"
    files = manifest(site)
    paths = {entry["hash"]: path for path, entry in files.items()}

    session = call("POST", f"{base}/scripts/{worker}/assets-upload-session", token, json={"manifest": files})
    completion = session["jwt"]  # if Cloudflare already has every file, this is all the next step needs
    for bucket in session.get("buckets") or []:
        parts = {h: (h, base64.b64encode((site / paths[h].lstrip("/")).read_bytes()), content_type(paths[h])) for h in bucket}
        uploaded = call("POST", f"{base}/assets/upload", session["jwt"], params={"base64": "true"}, files=parts)
        completion = uploaded.get("jwt") or completion

    metadata = {"assets": {"jwt": completion, "config": ASSET_CONFIG}, "compatibility_date": COMPATIBILITY_DATE}
    call("PUT", f"{base}/scripts/{worker}", token, files={"metadata": (None, json.dumps(metadata), "application/json")})
    # The site lives at its own domains only: no workers.dev copy and no preview URLs of old versions.
    call("POST", f"{base}/scripts/{worker}/subdomain", token, json={"enabled": False, "previews_enabled": False})
    for domain in domains:
        call("PUT", f"{base}/domains", token, json={"hostname": domain, "service": worker})
