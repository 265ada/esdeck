"""Keep a record of every run, and hand the lot over for analysis.

Each command writes a transcript as it goes - the same text that appeared on
screen, timestamped and kept. That matters most for the runs nobody is watching:
a sort left going overnight, a scan on a machine in another room. When something
comes out wrong afterwards, the question is always "what did it actually do",
and the honest answer needs a record rather than a memory of a window that has
since scrolled or been closed.

Logs are plain text, one file per run, and `export` collects them into a single
zip to send on.
"""

from __future__ import annotations

import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR

LOG_DIR = CONFIG_DIR / "logs"

#: Enough history to cover a few days of use without growing without limit.
KEEP = 60


class Tee:
    """Writes to the console and to a log file at once.

    Carriage returns are turned into newlines on the way to the file: a status
    line redrawing itself in place is one line on screen and an unreadable
    smear in a text file.
    """

    def __init__(self, stream, handle):
        self._stream = stream
        self._handle = handle

    def write(self, text):
        self._stream.write(text)
        try:
            self._handle.write(text.replace("\r", "\n"))
        except (OSError, ValueError):
            pass
        return len(text)

    def flush(self):
        for target in (self._stream, self._handle):
            try:
                target.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        try:
            return self._stream.isatty()
        except (AttributeError, ValueError):
            return False

    def __getattr__(self, name):
        return getattr(self._stream, name)


def path_for(command: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in command)[:40]
    return LOG_DIR / f"{stamp}_{safe or 'esdeck'}.log"


def start(command: str):
    """Begin recording this run. Returns (restore_callable, log_path)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        dest = path_for(command)
        handle = open(dest, "w", encoding="utf-8", errors="replace")
    except OSError:
        return (lambda: None), None      # never let logging break the command

    handle.write(f"esdeck {command}\n")
    handle.write(f"started {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    handle.write("-" * 72 + "\n")
    handle.flush()

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout = Tee(original_out, handle)
    sys.stderr = Tee(original_err, handle)
    began = time.monotonic()

    def restore():
        sys.stdout, sys.stderr = original_out, original_err
        try:
            handle.write("-" * 72 + "\n")
            handle.write(f"finished after {time.monotonic() - began:.1f}s\n")
            handle.close()
        except (OSError, ValueError):
            pass
        prune()

    return restore, dest


def entries() -> list:
    """Every log kept, newest first."""
    if not LOG_DIR.is_dir():
        return []
    return sorted((p for p in LOG_DIR.glob("*.log") if p.is_file()),
                  key=lambda p: p.name, reverse=True)


def prune(keep: int = KEEP) -> int:
    """Drop the oldest logs beyond the limit."""
    removed = 0
    for old in entries()[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def export(dest_dir) -> tuple:
    """Zip every log into dest_dir. Returns (path, count, bytes)."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = dest_dir / f"esdeck-logs_{stamp}.zip"
    files = entries()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            try:
                zf.write(f, arcname=f.name)
            except OSError:
                continue
        # What the logs are about is as useful as the logs themselves.
        zf.writestr("about.txt", _about(files))
    return out, len(files), out.stat().st_size


def _about(files) -> str:
    from . import __version__
    lines = [f"esdeck {__version__}",
             f"exported {datetime.now():%Y-%m-%d %H:%M:%S}",
             f"{len(files)} run(s) recorded", ""]
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        lines.append(f"  {f.name}  ({size} bytes)")
    return "\n".join(lines) + "\n"
