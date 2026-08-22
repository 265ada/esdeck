"""Identify a disc image by looking inside it.

Disc extensions are useless for detection - ES-DE maps .cue to 73 different
systems and .bin to 122. The disc itself, however, says what it is: every
console stamps a signature in its boot area. Reading a couple of megabytes is
far more reliable than guessing from a filename.

Every function here is read-only and failure-tolerant: an unreadable or
unrecognised image simply returns None.
"""

from __future__ import annotations

import re
from pathlib import Path

#: How much of the image to search. Boot signatures live in the first sectors,
#: but .bin images carry 16 sectors of lead-in, so allow some slack.
SNIFF_BYTES = 4 * 1024 * 1024

#: (signature, ES-DE system key). Order matters - the first hit wins, so the
#: more specific signatures come first.
DISC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"SEGA SEGAKATANA", "dreamcast"),
    (b"SEGA SEGASATURN", "saturn"),
    (b"SEGADISCSYSTEM", "megacd"),
    (b"SEGABOOTDISC", "megacd"),
    (b"PC Engine CD-ROM SYSTEM", "pcenginecd"),
    (b"PC-FX:Hu_CD-ROM", "pcfx"),
    (b"iso9660\x00CD-i", "cdimono1"),
    (b"UMD MEDIA FILE", "psp"),
    (b"PSP GAME", "psp"),
)

#: Magic numbers at fixed offsets: (offset, magic, system).
MAGIC_AT_OFFSET: tuple[tuple[int, bytes, str], ...] = (
    (0x1C, b"\xc2\x33\x9f\x3d", "gc"),      # GameCube disc magic
    (0x18, b"\x5d\x1c\x9e\xa3", "wii"),     # Wii disc magic
)

_CUE_FILE_RE = re.compile(r'FILE\s+"([^"]+)"', re.I)
_BOOT2_RE = re.compile(rb"BOOT2\s*[=:]", re.I)
_BOOT_RE = re.compile(rb"BOOT\s*[=:]", re.I)


def cue_first_file(cue_path: Path) -> Path | None:
    """The data file a .cue sheet points at, resolved next to the cue."""
    try:
        text = Path(cue_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _CUE_FILE_RE.search(text)
    if not m:
        return None
    target = Path(cue_path).parent / m.group(1)
    return target if target.is_file() else None


def _read_head(path: Path, size: int = SNIFF_BYTES) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


def _playstation_generation(head: bytes) -> str | None:
    """Tell PS1 from PS2 - both stamp 'PLAYSTATION' on the disc.

    The difference is in SYSTEM.CNF: PS2 boots via BOOT2=, PS1 via BOOT=.
    """
    if b"PLAYSTATION" not in head and b"Sony Computer Entertainment" not in head:
        return None
    idx = head.find(b"SYSTEM.CNF")
    if idx != -1:
        window = head[idx:idx + 8192]
        if _BOOT2_RE.search(window):
            return "ps2"
        if _BOOT_RE.search(window):
            return "psx"
    # Older PS1 pressings name the executable directly.
    if b"PSX.EXE" in head or b"SLUS" in head or b"SCUS" in head or b"SLES" in head:
        return "psx"
    return "psx"


def identify_image(path: Path) -> str | None:
    """The ES-DE system key for a disc image, or None if it cannot be told."""
    path = Path(path)
    if path.suffix.lower() == ".cue":
        target = cue_first_file(path)
        if target is None:
            return None
        path = target

    head = _read_head(path)
    if not head:
        return None

    for offset, magic, key in MAGIC_AT_OFFSET:
        if head[offset:offset + len(magic)] == magic:
            return key

    for sig, key in DISC_SIGNATURES:
        if sig in head:
            return key

    return _playstation_generation(head)


#: Extensions whose contents we can read directly.
SNIFFABLE = (".cue", ".bin", ".iso", ".img", ".ccd", ".mdf", ".gdi", ".cdi")


def is_chd(path: Path) -> bool:
    """CHD is a compressed container - its payload cannot be read without chdman."""
    return _read_head(Path(path), 8).startswith(b"MComprHD")


def identify(path: Path) -> str | None:
    """The ES-DE system for a file, or None when it cannot be determined.

    CHD deliberately returns None: the disc data is compressed, so identifying
    it would need chdman. Those stay ambiguous and ask the user instead.
    """
    if Path(path).suffix.lower() in SNIFFABLE:
        return identify_image(path)
    return None
