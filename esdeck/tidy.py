"""Repair an existing ROM library.

`esdeck sync` gets new games right, but a library built before those rules
existed - or by hand, or by another tool - can still show a game once per file
and hold the same game twice in different formats. This finds both without
changing anything until told to.

Nothing here deletes a game. Duplicates are reported for a human to judge,
because "which of these two copies do I want" is not a decision a script should
make about someone's collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import systems as sysmod
from .plan import ENTRY_POINT_ORDER, MULTIFILE_EXTS
from .scan import base_stem

#: Files that are data for another file rather than a game in their own right.
DATA_EXTS = {".bin", ".img", ".sub", ".ccd", ".mds", ".mdf", ".raw", ".iso"}


@dataclass
class Group:
    """Files in one system folder that belong to the same game."""
    system: str
    title: str
    files: list = field(default_factory=list)

    @property
    def entry(self):
        """The file ES-DE should show for this game."""
        for ext in ENTRY_POINT_ORDER:
            for f in self.files:
                if f.suffix.lower() == ext:
                    return f
        return self.files[0] if self.files else None

    @property
    def extras(self) -> list:
        """Everything that should be hidden so one game shows once."""
        entry = self.entry
        return [f for f in self.files
                if f is not entry and f.suffix.lower() in DATA_EXTS]


def is_hidden(path: Path) -> bool:
    try:
        import os
        return bool(os.stat(path).st_file_attributes & 0x02)   # FILE_ATTRIBUTE_HIDDEN
    except (AttributeError, OSError):
        return False


def group_system(system_dir: Path) -> list[Group]:
    """Group the loose files of one system folder into games."""
    system_dir = Path(system_dir)
    try:
        files = [p for p in system_dir.iterdir() if p.is_file()]
    except OSError:
        return []
    groups: dict[str, Group] = {}
    for f in files:
        key = base_stem(f.stem)
        g = groups.setdefault(key, Group(system_dir.name, key))
        g.files.append(f)
    return list(groups.values())


def redundant_entries(rom_dir: Path) -> list[tuple[Path, str]]:
    """Files ES-DE lists as games but which are really data for another file.

    A .cue and its .bin are one game shown twice; the .bin should be hidden.
    """
    out = []
    for sysdir in sorted(p for p in Path(rom_dir).iterdir() if p.is_dir()):
        for group in group_system(sysdir):
            if len(group.files) < 2:
                continue
            if not any(f.suffix.lower() in MULTIFILE_EXTS for f in group.files):
                continue
            entry = group.entry
            for extra in group.extras:
                if not is_hidden(extra):
                    out.append((extra, f"data for {entry.name}" if entry else "data file"))
    return out


def unhidden_disc_folders(rom_dir: Path) -> list[tuple[Path, str]]:
    """Multi-disc subfolders that should be hidden behind their .m3u."""
    out = []
    for sysdir in sorted(p for p in Path(rom_dir).iterdir() if p.is_dir()):
        playlists = {p.stem for p in sysdir.glob("*.m3u")}
        for sub in sorted(p for p in sysdir.iterdir() if p.is_dir()):
            if sub.name in playlists and not is_hidden(sub):
                out.append((sub, f"discs behind {sub.name}.m3u"))
    return out


#: Folders that look like a library but are really the artefact of answering
#: the drive question with a bare letter. "G" is a relative path, so "G\ROMs"
#: was created next to the script instead of on the G: drive.
LIBRARY_MARKERS = ("ROMs", "Incoming")


@dataclass
class Stray:
    path: Path
    files: int          # real files inside; 0 means it is just an empty tree

    @property
    def safe_to_remove(self) -> bool:
        return self.files == 0

    def describe(self) -> str:
        if self.safe_to_remove:
            return f"{self.path}  (empty - safe to remove)"
        return (f"{self.path}  ({self.files} file(s) inside - NOT removed, "
                f"move them somewhere real first)")


def stray_libraries(near) -> list[Stray]:
    """Mis-created library folders sitting in `near`.

    Only single-letter folders are considered, and only when they contain a
    ROMs or Incoming folder - that combination does not happen by accident. A
    stray holding actual files is reported but never deleted, because by then
    it is somebody's library, wrong place or not.
    """
    near = Path(near)
    out = []
    try:
        entries = [p for p in near.iterdir() if p.is_dir()]
    except OSError:
        return []
    for d in entries:
        if len(d.name) != 1 or not d.name.isalpha():
            continue
        if not any((d / m).is_dir() for m in LIBRARY_MARKERS):
            continue
        files = sum(1 for p in d.rglob("*") if p.is_file())
        out.append(Stray(d, files))
    return out


def remove_stray(stray: Stray, *, dry_run: bool = True) -> str:
    """Delete an empty stray library tree. Never touches one holding files."""
    if not stray.safe_to_remove:
        return f"kept {stray.path} - it has {stray.files} file(s) in it"
    if dry_run:
        return f"would remove {stray.path}"
    import shutil
    shutil.rmtree(stray.path, ignore_errors=True)
    return f"removed {stray.path}"


@dataclass
class Duplicate:
    system: str
    title: str
    paths: list

    def describe(self) -> str:
        names = ", ".join(p.name for p in self.paths)
        return f"{self.system}: {self.title} -> {names}"


def duplicates(rom_dir: Path) -> list[Duplicate]:
    """The same game present more than once in a system, in different formats.

    Only entry-point files count, so a .cue and its .bin are not a duplicate,
    but 'Game.zip' alongside 'Game.sfc' is.
    """
    out = []
    for sysdir in sorted(p for p in Path(rom_dir).iterdir() if p.is_dir()):
        by_title: dict[str, list] = {}
        for f in sysdir.iterdir():
            if not f.is_file() or is_hidden(f):
                continue
            if f.suffix.lower() in DATA_EXTS:
                continue
            if not sysmod.systems_for_ext(f.suffix):
                continue
            by_title.setdefault(base_stem(f.stem), []).append(f)
        for title, paths in sorted(by_title.items()):
            if len(paths) > 1:
                out.append(Duplicate(sysdir.name, title, sorted(paths)))
    return out


def cross_system_duplicates(rom_dir: Path) -> list[Duplicate]:
    """The same title filed under more than one system - usually a misfile."""
    seen: dict[str, list] = {}
    for sysdir in sorted(p for p in Path(rom_dir).iterdir() if p.is_dir()):
        for f in sysdir.iterdir():
            if not f.is_file() or is_hidden(f) or f.suffix.lower() in DATA_EXTS:
                continue
            if not sysmod.systems_for_ext(f.suffix):
                continue
            seen.setdefault(base_stem(f.stem), []).append(f)
    out = []
    for title, paths in sorted(seen.items()):
        systems = {p.parent.name for p in paths}
        if len(systems) > 1:
            out.append(Duplicate("/".join(sorted(systems)), title, sorted(paths)))
    return out
