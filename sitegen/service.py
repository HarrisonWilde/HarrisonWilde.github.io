"""Background jobs on this Mac, as launchd agents: the private site, and publishing on a schedule."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

from .config import ROOT

AGENTS = {
    "private": {
        "label": "com.harrisonwilde.hwil.private",
        "log": "hwil-private.log",
        # --strict exits if an address (e.g. the WireGuard one) isn't up yet; launchd retries after 30 s.
        "command": ["serve", "--private", "--strict"],
        "when": {"RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30},
        "installed": "the private site now starts at login and restarts if it stops.",
    },
    "publish": {
        "label": "com.harrisonwilde.wilde-page.publish",
        "log": "wilde-page-publish.log",
        "command": ["deploy", "--yes", "--if-changed"],
        "when": {"StartInterval": 3600},  # launchd catches up once when the Mac wakes
        "installed": "the site now publishes every hour if anything has changed, while this Mac is on.",
    },
}


def plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def install(name: str) -> None:
    agent = AGENTS[name]
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    log = Path.home() / "Library" / "Logs" / agent["log"]
    plist = {
        "Label": agent["label"],
        "ProgramArguments": [uv, "run", "hw.py", *agent["command"]],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        **agent["when"],
    }
    uninstall(name, quiet=True)
    path = plist_path(agent["label"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
    print(f"Installed {path.name}: {agent['installed']}\nLog: {log}")


def uninstall(name: str, quiet: bool = False) -> None:
    label = AGENTS[name]["label"]
    target = f"gui/{os.getuid()}/{label}"
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    for _ in range(50):  # bootout finishes asynchronously; bootstrapping too soon fails with error 5
        if subprocess.run(["launchctl", "print", target], capture_output=True).returncode != 0:
            break
        time.sleep(0.1)
    path = plist_path(label)
    existed = path.exists()
    path.unlink(missing_ok=True)
    if not quiet:
        print(f"Removed {path.name}." if existed else "Not installed.")
