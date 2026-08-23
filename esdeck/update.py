"""Keep esdeck current without anyone re-downloading a ZIP.

Copying a fresh .bat out of a download does not update esdeck - the batch files
are launchers, and the code they run is the installed package. That caught us
out once already, so the launcher checks GitHub itself and reinstalls when
there is something newer.

Checks are cheap: a single small file is fetched to read the version. The full
download only happens when the version actually differs.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import CONFIG_DIR

REPO = "265ada/esdeck"
BRANCH = "master"
#: The API returns the current file; raw.githubusercontent is CDN-cached for
#: several minutes and reported a stale version straight after a push.
VERSION_URL = (f"https://api.github.com/repos/{REPO}/contents/esdeck/__init__.py"
               f"?ref={BRANCH}")
VERSION_URL_FALLBACK = (f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
                        f"/esdeck/__init__.py")
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
USER_AGENT = f"esdeck/{__version__} (+https://github.com/{REPO})"
TIMEOUT = 60

#: Do not hammer GitHub on every launch.
CHECK_INTERVAL = 6 * 3600
STAMP = CONFIG_DIR / "last-update-check"

_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


@dataclass
class Available:
    version: str
    current: str

    @property
    def newer(self) -> bool:
        return _as_tuple(self.version) > _as_tuple(self.current)


def _as_tuple(v: str) -> tuple:
    """Compare versions numerically, so 0.10.0 beats 0.9.0."""
    parts = []
    for chunk in re.split(r"[.\-+]", v or ""):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts + [0] * (4 - len(parts)))


def _get(url: str, timeout: int = TIMEOUT, raw: bool = False) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}
    if raw:
        headers["Accept"] = "application/vnd.github.raw"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def latest_version() -> str | None:
    """The version on GitHub, or None if it cannot be reached."""
    for url, raw in ((VERSION_URL, True), (VERSION_URL_FALLBACK, False)):
        try:
            text = _get(url, timeout=20, raw=raw).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        m = _VERSION_RE.search(text)
        if m:
            return m.group(1)
    return None


def check(force: bool = False) -> Available | None:
    """Whether an update exists. Returns None when GitHub cannot be reached."""
    if not force and _checked_recently():
        return None
    remote = latest_version()
    _touch_stamp()
    if remote is None:
        return None
    return Available(remote, __version__)


def _checked_recently() -> bool:
    try:
        return (time.time() - STAMP.stat().st_mtime) < CHECK_INTERVAL
    except OSError:
        return False


def _touch_stamp() -> None:
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def download_and_install(*, bat_dir: Path | None = None, log=print) -> bool:
    """Fetch the current source and reinstall the package.

    bat_dir, if given, also receives fresh copies of the .bat files, so the
    launcher a person double-clicks stays current too.
    """
    log("  downloading the latest esdeck...")
    try:
        payload = _get(ZIP_URL, timeout=180)
    except (urllib.error.URLError, OSError) as exc:
        log(f"  could not download: {exc}")
        return False

    tmp = Path(tempfile.mkdtemp(prefix="esdeck-update-"))
    try:
        try:
            zipfile.ZipFile(io.BytesIO(payload)).extractall(tmp)
        except zipfile.BadZipFile:
            log("  the download was not a valid archive")
            return False

        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if not roots:
            log("  the download looked empty")
            return False
        src = roots[0]

        log("  installing...")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", str(src),
             "--quiet", "--disable-pip-version-check"],
            capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            log(f"  install failed: {(proc.stderr or proc.stdout).strip()[:300]}")
            return False

        if bat_dir is not None:
            copied = _refresh_bats(src, Path(bat_dir), log=log)
            if copied:
                log(f"  refreshed {copied} launcher file(s)")
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _refresh_bats(src: Path, dest: Path, *, log=print) -> int:
    """Copy the .bat files across, but only where they actually differ."""
    copied = 0
    for bat in sorted(src.glob("*.bat")):
        target = dest / bat.name
        try:
            if target.is_file() and target.read_bytes() == bat.read_bytes():
                continue
            shutil.copy2(bat, target)
            copied += 1
        except OSError as exc:
            log(f"  could not update {bat.name}: {exc}")
    return copied
