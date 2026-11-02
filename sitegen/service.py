"""Keep the private site running in the background as a launchd agent (like fitzcarraldo's server)."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

from .config import ROOT

LABEL = "com.harrisonwilde.hwil.private"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "hwil-private.log"


def install() -> None:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    agent = {
        "Label": LABEL,
        # --strict exits if an address (e.g. the WireGuard one) isn't up yet; launchd retries after 30 s.
        "ProgramArguments": [uv, "run", "hw.py", "serve", "--private", "--strict"],
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
    }
    uninstall(quiet=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    with PLIST.open("wb") as f:
        plistlib.dump(agent, f)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True)
    print(f"Installed {PLIST.name}: the private site now starts at login and restarts if it stops.\nLog: {LOG}")


def uninstall(quiet: bool = False) -> None:
    target = f"gui/{os.getuid()}/{LABEL}"
    subprocess.run(["launchctl", "bootout", target], capture_output=True)
    for _ in range(50):  # bootout finishes asynchronously; bootstrapping too soon fails with error 5
        if subprocess.run(["launchctl", "print", target], capture_output=True).returncode != 0:
            break
        time.sleep(0.1)
    existed = PLIST.exists()
    PLIST.unlink(missing_ok=True)
    if not quiet:
        print(f"Removed {PLIST.name}." if existed else "Not installed.")
