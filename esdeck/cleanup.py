"""Clean up a library sorted by an older, buggier esdeck.

The specific damage: ES-DE lists .png as a valid extension for pico8 and tic80,
so a collection with box art beside the ROMs produced a PICO-8 system full of
entries like "007 - The World Is Not Enough-image" - N64 artwork filed as games.

This finds artwork sitting in ROM folders and removes it, then clears the empty
folders left behind. It is careful about one thing: a genuine PICO-8 cartridge
really is a .png, so those are identified and kept.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import systems as sysmod

#: PICO-8 cartridges are 160x205 PNGs carrying the cart data in the low bits.
PICO8_SIZE = (160, 205)

#: What ES-DE calls the artwork it scrapes. A file whose name ends in one of
#: these is scraper output no matter what extension it wears, and no matter
#: what folder it landed in - "007 - The World Is Not Enough-image" is artwork,
#: not a game. Name alone is enough, so this catches media types we have never
#: heard of, and is never spared as a cartridge.
SCRAPER_SUFFIXES = (
    "-image", "-thumb", "-marquee", "-screenshot", "-titlescreen", "-title",
    "-fanart", "-boxback", "-boxfront", "-box2d", "-box3d", "-3dbox",
    "-backcover", "-cover", "-physicalmedia", "-manual", "-video", "-miximage",
    "-wheel", "-logo", "-bezel",
)


def scraper_name(path) -> bool:
    """True when the filename is one ES-DE's scraper would have written."""
    return Path(path).stem.lower().endswith(SCRAPER_SUFFIXES)


def png_dimensions(path: Path) -> tuple | None:
    """(width, height) of a PNG without decoding it, or None if not a PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
    except OSError:
        return None
    if not head.startswith(b"\x89PNG\r\n\x1a\n") or len(head) < 24:
        return None
    try:
        return struct.unpack(">II", head[16:24])
    except struct.error:
        return None


def is_pico8_cart(path: Path) -> bool:
    """True for a real PICO-8 cartridge, which is legitimately a .png."""
    if Path(path).suffix.lower() != ".png":
        return False
    dims = png_dimensions(Path(path))
    if dims == PICO8_SIZE:
        return True
    # Some carts are exported at other sizes but carry a pico-8 text chunk.
    try:
        data = Path(path).read_bytes()[:65536]
    except OSError:
        return False
    return b"pico-8" in data.lower()


@dataclass
class Junk:
    path: Path
    system: str
    size: int
    reason: str

    def describe(self) -> str:
        return f"{self.system}/{self.path.name}  ({self.reason})"


@dataclass
class Report:
    junk: list = field(default_factory=list)
    kept: list = field(default_factory=list)     # (path, why)
    empty_systems: list = field(default_factory=list)

    @property
    def reclaimable(self) -> int:
        return sum(j.size for j in self.junk)


def find_junk(rom_dir: Path, *, progress=None) -> Report:
    """Artwork and stray media filed as games inside the ROM library."""
    rom_dir = Path(rom_dir)
    report = Report()
    if not rom_dir.is_dir():
        return report

    for sysdir in sorted(p for p in rom_dir.iterdir() if p.is_dir()):
        if sysdir.name.startswith("."):
            continue
        if progress is not None:
            progress.advance(label=f"checking {sysdir.name}")
        for f in sysdir.rglob("*"):
            if not f.is_file():
                continue
            if progress is not None:
                progress.advance(items=1)
            scraped = scraper_name(f)
            if not scraped and not sysmod.is_media(f):
                continue
            # A cartridge is only ever spared on the strength of its contents,
            # and never when it is wearing a scraper's name.
            if not scraped and is_pico8_cart(f):
                report.kept.append((f, "a real PICO-8 cartridge, not artwork"))
                continue
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            report.junk.append(
                Junk(f, sysdir.name, size,
                     "scraped artwork" if scraped else "artwork filed as a game"))
    return report


def remove(report: Report, *, dry_run: bool = True, log=print) -> tuple[int, int]:
    """Delete the junk. Returns (files removed, bytes freed)."""
    removed = freed = 0
    for j in report.junk:
        log(f"  remove {j.describe()}")
        if dry_run:
            removed += 1
            freed += j.size
            continue
        try:
            j.path.unlink()
        except OSError as exc:
            log(f"  ERROR  {j.path.name}: {exc}")
            continue
        removed += 1
        freed += j.size
    return removed, freed


def empty_dirs(rom_dir: Path) -> list[Path]:
    """System folders and subfolders left with nothing in them."""
    rom_dir = Path(rom_dir)
    out = []
    if not rom_dir.is_dir():
        return out
    for sysdir in sorted(p for p in rom_dir.iterdir() if p.is_dir()):
        for d in sorted(sysdir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir():
                try:
                    if not any(d.iterdir()):
                        out.append(d)
                except OSError:
                    continue
        # The system folder itself, last, once anything inside it has gone.
        # ES-DE lists a system because its folder exists, so leaving an empty
        # one behind means the system stays on screen with nothing in it.
        try:
            if not any(f.is_file() for f in sysdir.rglob("*")):
                out.append(sysdir)
        except OSError:
            pass
    return out


def prune_empty(dirs, *, dry_run: bool = True, log=print) -> int:
    pruned = 0
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            if any(d.iterdir()):
                continue
        except OSError:
            continue
        log(f"  rmdir  {d.name}")
        pruned += 1
        if not dry_run:
            try:
                d.rmdir()
            except OSError:
                pruned -= 1
    return pruned


def systems_left_empty(rom_dir: Path) -> list[str]:
    """Systems that now hold nothing - ES-DE will simply stop listing them."""
    rom_dir = Path(rom_dir)
    out = []
    if not rom_dir.is_dir():
        return out
    for sysdir in sorted(p for p in rom_dir.iterdir() if p.is_dir()):
        try:
            if not any(f.is_file() for f in sysdir.rglob("*")):
                out.append(sysdir.name)
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------
# Stale ES-DE state
# --------------------------------------------------------------------------
#
# Deleting the files is only half of it. ES-DE builds its list of systems once,
# at startup, and keeps a gamelist.xml per system describing what it found. A
# system whose games are gone still has its gamelist, and with ParseGamelistOnly
# turned on ES-DE will happily go on listing games that no longer exist. That is
# what leaves a PICO-8 full of Nintendo 64 titles on screen after a clean.


def library_is_intact(rom_dir) -> bool:
    """Whether the library looks like a library, rather than a missing drive.

    Everything below decides that a system is dead by finding no games for it.
    On a library that is simply not there - an unplugged drive, a path typed
    wrong, a sort that has not run yet - *every* system meets that test, and
    the result would be deleting every gamelist and all the scraped artwork
    for a collection that is perfectly fine. So: unless at least one system
    still has games, assume the library is missing rather than empty, and
    touch nothing.
    """
    rom_dir = Path(rom_dir)
    if not rom_dir.is_dir():
        return False
    try:
        for sysdir in rom_dir.iterdir():
            if sysdir.is_dir() and any(f.is_file() for f in sysdir.rglob("*")):
                return True
    except OSError:
        return False
    return False


def stale_gamelists(es_config_dir, rom_dir) -> list:
    """Gamelists for systems that no longer have any games on disk."""
    gl_root = Path(es_config_dir) / "gamelists"
    rom_dir = Path(rom_dir)
    out = []
    if not gl_root.is_dir() or not library_is_intact(rom_dir):
        return out
    for d in sorted(p for p in gl_root.iterdir() if p.is_dir()):
        sysdir = rom_dir / d.name
        try:
            has_games = sysdir.is_dir() and any(
                f.is_file() for f in sysdir.rglob("*"))
        except OSError:
            has_games = True                 # unreadable: leave it well alone
        if not has_games:
            out.append(d)
    return out


def stale_media(es_config_dir, rom_dir, media_dir=None) -> list:
    """Scraped media folders for systems that no longer have any games."""
    root = Path(media_dir) if media_dir else Path(es_config_dir) / "downloaded_media"
    rom_dir = Path(rom_dir)
    out = []
    if not root.is_dir() or not library_is_intact(rom_dir):
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        sysdir = rom_dir / d.name
        try:
            has_games = sysdir.is_dir() and any(
                f.is_file() for f in sysdir.rglob("*"))
        except OSError:
            has_games = True
        if not has_games:
            out.append(d)
    return out


def remove_tree(path: Path, *, dry_run: bool = True) -> int:
    """Delete a folder and everything under it. Returns bytes freed."""
    import shutil
    freed = 0
    try:
        for f in Path(path).rglob("*"):
            if f.is_file():
                try:
                    freed += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        return 0
    if not dry_run:
        shutil.rmtree(path, ignore_errors=True)
    return freed
