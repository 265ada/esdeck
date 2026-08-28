"""Find the copies still sitting in the browser's Downloads folder.

A game usually arrives twice over: the browser leaves the download where it
fell, and then a copy is dropped into the folder esdeck sorts from. Clearing
the drop folder therefore reclaims half the space, and a 40 GB archive can sit
in Downloads for months with nothing pointing at it.

Downloads is somebody's own folder, though, holding all sorts of things that
have nothing to do with games. So the bar for suggesting a file here is higher
than for the drop folder, and two questions have to be answered "yes":

  * is this file a game, or an archive of one?
  * is it demonstrably already in the library?

A plain file is answered by content: byte for byte identical to something in
the library. An archive cannot be compared that way - it was unpacked, so
nothing in the library looks like it - so it is answered by what is inside it:
if every game file it contains is present in the library, the archive has been
installed and the download is a spare copy.

Nothing here deletes anything. It reports, and the caller asks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import archives, systems as sysmod
from .clean import same_file

#: The Downloads known-folder id, for the registry lookup below.
_DOWNLOADS_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"

#: An archive whose members are mostly present counts as installed. Not all:
#: a set can legitimately lose a file to a name clash or a skipped duplicate,
#: and demanding perfection would report nothing on real libraries.
INSTALLED_RATIO = 0.9


@dataclass
class Candidate:
    path: Path
    size: int
    reason: str
    matched: int = 0
    total: int = 0

    def describe(self) -> str:
        extra = f"  ({self.matched}/{self.total} inside)" if self.total else ""
        return f"{self.path.name}  -  {self.reason}{extra}"


@dataclass
class Report:
    found: list = field(default_factory=list)
    folder: Path | None = None
    skipped_unmatched: int = 0

    @property
    def reclaimable(self) -> int:
        return sum(c.size for c in self.found)


def folder() -> Path | None:
    """Where this account's Downloads folder actually is.

    Asked of Windows rather than assumed: it can be moved, and OneDrive moves
    it without asking. A guessed path that does not exist reports nothing and
    looks like a clean machine.
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        try:
            raw, _ = winreg.QueryValueEx(key, _DOWNLOADS_GUID)
            path = Path(os.path.expandvars(raw))
            if path.is_dir():
                return path
        finally:
            key.Close()
    except (ImportError, OSError, ValueError):
        pass

    for guess in (Path.home() / "Downloads",
                  Path.home() / "OneDrive" / "Downloads"):
        if guess.is_dir():
            return guess
    return None


def _library_names(roots) -> dict:
    """{lowercase filename: [paths]} for everything in the library."""
    index: dict[str, list] = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                index.setdefault(fn.lower(), []).append(Path(dirpath) / fn)
    return index


#: Trailing " (1)", " (2)" that browsers add to a repeated download.
_DUPE_SUFFIX = re.compile(r"\s*\(\d+\)$")


def _base_name(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        return _DUPE_SUFFIX.sub("", name).lower()
    return (_DUPE_SUFFIX.sub("", stem) + "." + ext).lower()


def _archive_is_installed(path: Path, index: dict) -> tuple:
    """(installed?, matched, total) judged by the archive's own contents."""
    names = archives.members(path)
    if not names:
        return False, 0, 0
    wanted = [Path(n).name for n in names
              if Path(n).name and not sysmod.is_media(Path(n))]
    wanted = [n for n in wanted if not n.endswith("/")]
    if not wanted:
        return False, 0, 0
    matched = sum(1 for n in wanted if n.lower() in index)
    return (matched / len(wanted)) >= INSTALLED_RATIO, matched, len(wanted)


def survey(downloads_dir, library_roots, *, quick: bool = False) -> Report:
    """Downloads that are already in the library, and can go."""
    report = Report(folder=Path(downloads_dir) if downloads_dir else None)
    if not downloads_dir or not Path(downloads_dir).is_dir():
        return report

    index = _library_names(library_roots)
    by_base = {}
    for name, paths in index.items():
        by_base.setdefault(_base_name(name), []).extend(paths)

    for entry in sorted(Path(downloads_dir).iterdir()):
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue

        # A later volume of a split set is dealt with by its first part.
        if archives.is_later_volume(entry):
            continue

        if archives.is_archive(entry):
            installed, matched, total = _archive_is_installed(entry, index)
            if installed:
                report.found.append(Candidate(
                    entry, size, "everything inside it is in your library",
                    matched, total))
            else:
                report.skipped_unmatched += 1
            continue

        # A plain file: only its own contents will do.
        twins = by_base.get(_base_name(entry.name), [])
        if any(same_file(entry, t, quick=quick) for t in twins):
            report.found.append(Candidate(
                entry, size, "the same file is in your library"))
        else:
            report.skipped_unmatched += 1

    return report
