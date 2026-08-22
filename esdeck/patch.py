"""Apply ROM patches - translations, hacks and other mods.

A mod usually arrives as a patch file next to (or instead of) the ROM it
modifies: IPS, BPS or UPS. Applying one by hand means finding the right base
ROM, finding a patching tool, and not overwriting the original by mistake.

esdeck applies the patch itself, writes the result as a *new* file, and never
touches the base ROM. Where a format records a checksum of the ROM it expects,
that is verified first - patching the wrong base produces a broken game that
looks fine until it crashes hours in.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

PATCH_EXTS = (".ips", ".bps", ".ups")


class PatchError(Exception):
    """The patch could not be applied - wrong base ROM, or a bad patch file."""


@dataclass
class Result:
    output: Path
    format: str
    verified: bool          # base ROM checksum matched the patch's expectation
    note: str = ""


# --------------------------------------------------------------------------
# IPS - the oldest and simplest: a list of (offset, bytes) records.
# --------------------------------------------------------------------------

def apply_ips(base: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"PATCH"):
        raise PatchError("not an IPS patch (missing PATCH header)")
    out = bytearray(base)
    pos = 5
    while pos + 3 <= len(patch):
        if patch[pos:pos + 3] == b"EOF":
            break
        offset = int.from_bytes(patch[pos:pos + 3], "big")
        pos += 3
        if pos + 2 > len(patch):
            raise PatchError("truncated IPS patch")
        size = int.from_bytes(patch[pos:pos + 2], "big")
        pos += 2
        if size == 0:                      # RLE run
            if pos + 3 > len(patch):
                raise PatchError("truncated IPS RLE record")
            run = int.from_bytes(patch[pos:pos + 2], "big")
            value = patch[pos + 2]
            pos += 3
            chunk = bytes([value]) * run
        else:
            chunk = patch[pos:pos + size]
            pos += size
        if offset + len(chunk) > len(out):
            out.extend(b"\x00" * (offset + len(chunk) - len(out)))
        out[offset:offset + len(chunk)] = chunk
    return bytes(out)


# --------------------------------------------------------------------------
# UPS and BPS - both use variable-length numbers and carry CRC32s.
# --------------------------------------------------------------------------

def _read_vlq(data: bytes, pos: int) -> tuple[int, int]:
    """The variable-length number format shared by UPS and BPS."""
    value, shift = 0, 1
    while True:
        if pos >= len(data):
            raise PatchError("truncated patch")
        byte = data[pos]
        pos += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            break
        shift <<= 7
        value += shift
    return value, pos


def apply_ups(base: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"UPS1"):
        raise PatchError("not a UPS patch")
    pos = 4
    _in_size, pos = _read_vlq(patch, pos)
    out_size, pos = _read_vlq(patch, pos)

    out = bytearray(base) + bytearray(max(0, out_size - len(base)))
    del out[out_size:]

    body_end = len(patch) - 12          # three CRC32s at the tail
    index = 0
    while pos < body_end:
        skip, pos = _read_vlq(patch, pos)
        index += skip
        while pos < body_end:
            byte = patch[pos]
            pos += 1
            if byte == 0:
                break
            if index < len(out):
                out[index] ^= byte
            index += 1
        index += 1
    return bytes(out)


def apply_bps(base: bytes, patch: bytes) -> bytes:
    if not patch.startswith(b"BPS1"):
        raise PatchError("not a BPS patch")
    pos = 4
    source_size, pos = _read_vlq(patch, pos)
    target_size, pos = _read_vlq(patch, pos)
    metadata_size, pos = _read_vlq(patch, pos)
    pos += metadata_size

    if len(base) != source_size:
        raise PatchError(
            f"this patch expects a {source_size:,}-byte ROM but the base is "
            f"{len(base):,} bytes - it is for a different dump")

    out = bytearray()
    source_rel = target_rel = 0
    body_end = len(patch) - 12          # three CRC32s at the tail

    while pos < body_end:
        data, pos = _read_vlq(patch, pos)
        action, length = data & 3, (data >> 2) + 1
        if action == 0:                                  # SourceRead
            out += base[len(out):len(out) + length]
        elif action == 1:                                # TargetRead
            out += patch[pos:pos + length]
            pos += length
        else:                                            # Source/TargetCopy
            raw, pos = _read_vlq(patch, pos)
            offset = (-1 if raw & 1 else 1) * (raw >> 1)
            if action == 2:
                source_rel += offset
                out += base[source_rel:source_rel + length]
                source_rel += length
            else:
                target_rel += offset
                for _ in range(length):
                    out.append(out[target_rel])
                    target_rel += 1
    if len(out) != target_size:
        raise PatchError("patched output is the wrong size - patch may be corrupt")
    return bytes(out)


# --------------------------------------------------------------------------

def expected_source_crc(patch: bytes, fmt: str) -> int | None:
    """The CRC32 of the ROM a patch expects, when the format records one."""
    if fmt in ("bps", "ups") and len(patch) >= 12:
        return struct.unpack("<I", patch[-12:-8])[0]
    return None


def detect(patch: bytes) -> str:
    if patch.startswith(b"PATCH"):
        return "ips"
    if patch.startswith(b"BPS1"):
        return "bps"
    if patch.startswith(b"UPS1"):
        return "ups"
    raise PatchError("unrecognised patch format (not IPS, BPS or UPS)")


def apply_patch(base_path: Path, patch_path: Path, out_path: Path, *,
                dry_run: bool = False) -> Result:
    """Patch base_path with patch_path, writing a new file at out_path.

    The base ROM is never modified. If the patch records the checksum of the
    ROM it was made for, a mismatch stops the job rather than producing a
    subtly broken game.
    """
    base_path, patch_path, out_path = Path(base_path), Path(patch_path), Path(out_path)
    base = base_path.read_bytes()
    patch = patch_path.read_bytes()
    fmt = detect(patch)

    verified = False
    want = expected_source_crc(patch, fmt)
    if want is not None:
        got = zlib.crc32(base) & 0xFFFFFFFF
        if got != want:
            raise PatchError(
                f"{patch_path.name} is for a different dump of this game "
                f"(expects CRC {want:08x}, {base_path.name} is {got:08x})")
        verified = True

    if dry_run:
        return Result(out_path, fmt, verified, "not written (dry run)")

    result = {"ips": apply_ips, "bps": apply_bps, "ups": apply_ups}[fmt](base, patch)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result)
    return Result(out_path, fmt, verified)


def find_pairs(files) -> list[tuple]:
    """Match patch files to the base ROM they most likely apply to.

    A mod folder is usually one ROM plus one or more patches, so the pairing is
    simply "every patch against the only ROM here". With several ROMs present,
    names are matched instead, and anything ambiguous is left alone.
    """
    patches = [f for f in files if Path(f).suffix.lower() in PATCH_EXTS]
    roms = [f for f in files if Path(f).suffix.lower() not in PATCH_EXTS]
    if not patches or not roms:
        return []
    if len(roms) == 1:
        return [(roms[0], p) for p in patches]

    from .scan import base_stem
    pairs = []
    for p in patches:
        stem = base_stem(Path(p).stem)
        match = next((r for r in roms if base_stem(Path(r).stem) == stem), None)
        if match:
            pairs.append((match, p))
    return pairs
