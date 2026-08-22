"""A record of what each sort actually did, so it can be undone.

esdeck copies rather than moves, so a bad sort never destroys anything - but it
can still leave a few thousand files in the wrong place, and picking those out
by hand is worse than the original mess. Every run therefore writes down
exactly which files and folders it created.

Undo removes only what a run created, and only where the file is still exactly
as it was left: same size, same modification time. Anything touched since is
kept and reported, because by then it is not esdeck's to remove.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import CONFIG_DIR

HISTORY_DIR = CONFIG_DIR / "history"
MAX_RUNS = 20


@dataclass
class Created:
    path: str
    size: int = 0
    mtime: float = 0.0
    kind: str = "file"          # file | dir

    @classmethod
    def of(cls, path: Path, kind: str = "file") -> "Created":
        try:
            st = path.stat()
            return cls(str(path), st.st_size, st.st_mtime, kind)
        except OSError:
            return cls(str(path), 0, 0.0, kind)

    def unchanged(self) -> bool:
        """Whether this is still the file esdeck wrote, untouched since."""
        p = Path(self.path)
        if self.kind == "dir":
            return p.is_dir()
        try:
            st = p.stat()
        except OSError:
            return False
        return st.st_size == self.size and abs(st.st_mtime - self.mtime) < 2


@dataclass
class Run:
    started: float = field(default_factory=time.time)
    label: str = ""
    sources: list = field(default_factory=list)
    rom_dir: str = ""
    created: list = field(default_factory=list)   # Created, newest last

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started))

    @property
    def files(self) -> int:
        return sum(1 for c in self.created if c.kind == "file")

    @property
    def total_bytes(self) -> int:
        return sum(c.size for c in self.created if c.kind == "file")

    def add(self, path: Path, kind: str = "file") -> None:
        self.created.append(Created.of(Path(path), kind))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created"] = [asdict(c) if not isinstance(c, dict) else c
                        for c in self.created]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        run = cls(started=d.get("started", 0), label=d.get("label", ""),
                  sources=d.get("sources", []), rom_dir=d.get("rom_dir", ""))
        run.created = [Created(**c) for c in d.get("created", [])]
        return run


def save(run: Run) -> Path:
    """Write a run to the history, keeping only the most recent few."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{int(run.started)}.json"
    path.write_text(json.dumps(run.to_dict(), indent=1), encoding="utf-8")
    prune()
    return path


def prune(keep: int = MAX_RUNS) -> None:
    for old in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def runs() -> list[tuple]:
    """(path, Run) newest first."""
    if not HISTORY_DIR.is_dir():
        return []
    out = []
    for p in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            out.append((p, Run.from_dict(json.loads(p.read_text(encoding="utf-8")))))
        except (OSError, ValueError):
            continue
    return out


def latest() -> tuple | None:
    found = runs()
    return found[0] if found else None


@dataclass
class UndoResult:
    removed_files: int = 0
    removed_dirs: int = 0
    freed: int = 0
    kept: list = field(default_factory=list)     # (path, reason)

    def summary(self) -> str:
        return (f"{self.removed_files} file(s) and {self.removed_dirs} folder(s) "
                f"removed, {self.freed / 1_048_576:.0f} MB freed"
                + (f", {len(self.kept)} kept" if self.kept else ""))


def undo(run: Run, *, dry_run: bool = True, log=print) -> UndoResult:
    """Remove what a run created, leaving anything since modified alone."""
    res = UndoResult()

    for c in reversed([c for c in run.created if c.kind == "file"]):
        p = Path(c.path)
        if not p.exists():
            continue
        if not c.unchanged():
            res.kept.append((c.path, "changed since the sort - not esdeck's to remove"))
            continue
        log(f"  remove {p.name}")
        res.removed_files += 1
        res.freed += c.size
        if not dry_run:
            try:
                p.unlink()
            except OSError as exc:
                res.kept.append((c.path, str(exc)))
                res.removed_files -= 1
                res.freed -= c.size

    # Folders last, deepest first, and only when empty - a folder that still
    # holds something was not created solely by this run.
    for c in sorted([c for c in run.created if c.kind == "dir"],
                    key=lambda c: len(Path(c.path).parts), reverse=True):
        p = Path(c.path)
        if not p.is_dir():
            continue
        try:
            if any(p.iterdir()):
                continue
        except OSError:
            continue
        log(f"  rmdir  {p.name}")
        res.removed_dirs += 1
        if not dry_run:
            try:
                p.rmdir()
            except OSError:
                res.removed_dirs -= 1
    return res


def forget(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def set_hidden_ok(path: Path) -> bool:
    """Windows hides files by attribute; undo needs them visible to delete."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80))
    except (AttributeError, OSError):
        return False
