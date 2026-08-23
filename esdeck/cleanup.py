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


def find_junk(rom_dir: Path) -> Report:
    """Artwork and stray media filed as games inside the ROM library."""
    rom_dir = Path(rom_dir)
    report = Report()
    if not rom_dir.is_dir():
        return report

    for sysdir in sorted(p for p in rom_dir.iterdir() if p.is_dir()):
        if sysdir.name.startswith("."):
            continue
        for f in sysdir.rglob("*"):
            if not f.is_file() or not sysmod.is_media(f):
                continue
            if is_pico8_cart(f):
                report.kept.append((f, "a real PICO-8 cartridge, not artwork"))
                continue
            try:
                size = f.stat().st_size
            except OSError:
                size = 0
            report.junk.append(
                Junk(f, sysdir.name, size, "artwork filed as a game"))
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
