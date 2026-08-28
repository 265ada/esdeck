"""Reclaim the drop folder after games have been filed into the library.

esdeck copies rather than moves, so nothing is lost if a sort goes wrong. The
cost is that every game briefly exists twice - a four-disc PSX game is 2.2 GB in
each place. This removes the drop-folder copy, but only after proving byte for
byte that the library copy is intact.

Deleting someone's game files is the most destructive thing esdeck can do, so:
every candidate is verified first, verification defaults to a full content hash,
and nothing is deleted without --yes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import archives, systems as sysmod

CHUNK = 1 << 20


def _human(n: int) -> str:
    from .progress import human_bytes
    return human_bytes(n)


#: How much of an archive has to be present before it counts as installed.
#: Not all of it: a set can lose a file to a name clash or a skipped duplicate,
#: and demanding perfection would keep archives that are plainly installed.
INSTALLED_RATIO = 0.9


@dataclass
class Candidate:
    source: Path
    library: Path
    size: int
    verified: bool = False
    reason: str = ""


@dataclass
class Report:
    safe: list = field(default_factory=list)      # verified duplicates
    unmatched: list = field(default_factory=list)  # not in the library
    mismatched: list = field(default_factory=list)  # same name, different bytes

    @property
    def reclaimable(self) -> int:
        return sum(c.size for c in self.safe)


def file_hash(path: Path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def same_file(a: Path, b: Path, *, quick: bool = False) -> bool:
    """Whether two files hold identical content.

    Size is checked first because it is free and rules out almost everything.
    Then the full content, unless quick is set - a size match alone is a fair
    bet but not proof, and this decides whether to delete someone's game.
    """
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    if quick:
        return True
    try:
        return file_hash(a) == file_hash(b)
    except OSError:
        return False


def archive_is_installed(path: Path, index: dict) -> tuple:
    """(installed?, matched, total) judged by what the archive contains.

    Artwork is ignored: esdeck never files it, so counting it would stop any
    archive containing box art from ever looking installed.
    """
    try:
        names = archives.members(path)
    except OSError:
        return False, 0, 0
    if not names:
        return False, 0, 0
    wanted = [Path(n).name for n in names if n and not n.endswith("/")]
    wanted = [n for n in wanted if n and not sysmod.is_media(Path(n))]
    if not wanted:
        return False, 0, 0
    matched = sum(1 for n in wanted if n.lower() in index)
    return (matched / len(wanted)) >= INSTALLED_RATIO, matched, len(wanted)


def _library_index(roots) -> dict:
    """{filename: [paths]} for everything currently in the library."""
    index: dict[str, list] = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                index.setdefault(fn.lower(), []).append(Path(dirpath) / fn)
    return index


def measure(source_dirs) -> tuple:
    """(files, bytes) in the drop folder, so verifying can show a real bar."""
    items = nbytes = 0
    for src_root in source_dirs:
        src_root = Path(src_root)
        if not src_root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(src_root):
            for fn in filenames:
                items += 1
                try:
                    nbytes += (Path(dirpath) / fn).stat().st_size
                except OSError:
                    pass
    return items, nbytes


def survey(source_dirs, library_roots, *, quick: bool = False,
           progress=None) -> Report:
    """Work out which drop-folder files are already safely in the library."""
    index = _library_index(library_roots)
    report = Report()

    for src_root in source_dirs:
        src_root = Path(src_root)
        if not src_root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(src_root):
            for fn in filenames:
                src = Path(dirpath) / fn
                try:
                    size = src.stat().st_size
                except OSError:
                    continue
                if progress is not None:
                    progress.advance(items=1, nbytes=size, label=fn)
                matches = index.get(fn.lower(), [])
                twin = next((m for m in matches
                             if same_file(src, m, quick=quick)), None)
                if twin is not None:
                    report.safe.append(Candidate(src, twin, size, True))
                    continue

                # No byte-for-byte twin. For an archive that is expected:
                # it was unpacked, so nothing in the library resembles it.
                # What it contains answers the question instead.
                if archives.is_later_volume(src):
                    # A volume of a set - its first part speaks for all of it.
                    report.unmatched.append(
                        Candidate(src, Path(), size, False,
                                  "part of a split archive"))
                    continue
                if archives.is_archive(src):
                    installed, got, total = archive_is_installed(src, index)
                    if installed:
                        report.safe.append(Candidate(
                            src, Path(), size, True,
                            f"all {total} file(s) inside are in the library"))
                        continue

                if not matches:
                    report.unmatched.append(
                        Candidate(src, Path(), size, False, "not in the library"))
                else:
                    report.mismatched.append(
                        Candidate(src, matches[0], size, False,
                                  "same name in the library but different content"))
    return report


def purge(report: Report, *, dry_run: bool = True, log=print) -> tuple[int, int]:
    """Delete the verified duplicates. Returns (files removed, bytes freed)."""
    removed = freed = 0
    for c in report.safe:
        why = f"  -  {c.reason}" if c.reason else ""
        log(f"  remove {c.source.name}  ({_human(c.size)}){why}")
        if dry_run:
            removed += 1
            freed += c.size
            continue
        try:
            c.source.unlink()
        except OSError as exc:
            log(f"  ERROR  {c.source.name}: {exc}")
            continue
        removed += 1
        freed += c.size
    return removed, freed


def prune_empty_dirs(source_dirs, *, dry_run: bool = True, log=print) -> int:
    """Remove folders left behind once their files are gone."""
    pruned = 0
    for src_root in source_dirs:
        src_root = Path(src_root)
        if not src_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(src_root, topdown=False):
            d = Path(dirpath)
            if d == src_root:
                continue
            if filenames or dirnames:
                continue
            log(f"  rmdir  {d.name}")
            pruned += 1
            if not dry_run:
                try:
                    d.rmdir()
                except OSError:
                    pass
    return pruned
