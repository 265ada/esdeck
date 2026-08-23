"""Turn a picture into a Windows icon, cropped to a circle.

The source artwork is usually a square image with the subject in a circle and
dead space in the corners. Windows shortcuts want an .ico, and the corners
should be transparent rather than black, so this crops to the inscribed circle,
makes everything outside it transparent, and writes a multi-size .ico.

Pure stdlib: PNG is just zlib-compressed scanlines, and an .ico can carry PNG
payloads directly on Vista and later. No image library needed.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ICO_SIZES = (256, 128, 64, 48, 32, 16)


class IconError(Exception):
    """The source image could not be used."""


# --------------------------------------------------------------------------
# Minimal PNG reading
# --------------------------------------------------------------------------

def _chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        yield tag, payload
        pos += 12 + length


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path) -> tuple:
    """(width, height, RGBA bytes) from a PNG, without an image library."""
    data = Path(path).read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise IconError(f"{Path(path).name} is not a PNG file")

    width = height = depth = colour = 0
    idat = bytearray()
    palette = b""
    trns = b""
    for tag, payload in _chunks(data):
        if tag == b"IHDR":
            width, height, depth, colour, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", payload[:13])
            if interlace:
                raise IconError("interlaced PNGs are not supported - re-save it")
            if depth != 8:
                raise IconError(f"{depth}-bit PNGs are not supported - re-save as 8-bit")
        elif tag == b"PLTE":
            palette = payload
        elif tag == b"tRNS":
            trns = payload
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break

    if not width or not height:
        raise IconError("could not read the image size")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None:
        raise IconError(f"unsupported PNG colour type {colour}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _y in range(height):
        filt = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if filt == 1:
                line[x] = (line[x] + a) & 0xFF
            elif filt == 2:
                line[x] = (line[x] + b) & 0xFF
            elif filt == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif filt == 4:
                line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        out += line
        prev = line

    return width, height, _to_rgba(bytes(out), width, height, colour, palette, trns)


def _to_rgba(pixels: bytes, width: int, height: int, colour: int,
             palette: bytes, trns: bytes) -> bytearray:
    rgba = bytearray(width * height * 4)
    n = width * height
    if colour == 6:                                   # RGBA already
        return bytearray(pixels)
    for i in range(n):
        if colour == 2:                               # RGB
            r, g, b = pixels[i * 3:i * 3 + 3]
            a = 255
        elif colour == 0:                             # greyscale
            r = g = b = pixels[i]
            a = 255
        elif colour == 4:                             # grey + alpha
            r = g = b = pixels[i * 2]
            a = pixels[i * 2 + 1]
        else:                                         # palette
            idx = pixels[i]
            r, g, b = palette[idx * 3:idx * 3 + 3]
            a = trns[idx] if idx < len(trns) else 255
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    return rgba


# --------------------------------------------------------------------------
# Cropping and resizing
# --------------------------------------------------------------------------

def circle_crop(width: int, height: int, rgba: bytearray) -> tuple:
    """Crop to the largest centred square, then make outside the circle clear."""
    side = min(width, height)
    ox, oy = (width - side) // 2, (height - side) // 2
    out = bytearray(side * side * 4)
    r = side / 2
    r2 = (r - 0.5) ** 2
    for y in range(side):
        dy = (y + 0.5) - r
        for x in range(side):
            si = ((y + oy) * width + (x + ox)) * 4
            di = (y * side + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
            dx = (x + 0.5) - r
            if dx * dx + dy * dy > r2:
                out[di + 3] = 0                       # outside the circle
    return side, out


def resize(side: int, rgba: bytearray, target: int) -> bytearray:
    """Nearest-neighbour resize - adequate for icons, and dependency-free."""
    out = bytearray(target * target * 4)
    for y in range(target):
        sy = min(side - 1, y * side // target)
        for x in range(target):
            sx = min(side - 1, x * side // target)
            si = (sy * side + sx) * 4
            di = (y * target + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return out


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def write_png(path: Path, side: int, rgba: bytearray) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    raw = bytearray()
    for y in range(side):
        raw.append(0)                                  # no filter
        raw += rgba[y * side * 4:(y + 1) * side * 4]
    body = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))
    Path(path).write_bytes(body)


def _dib_bytes(side: int, rgba: bytearray) -> bytes:
    """One icon entry in the classic BMP/DIB form.

    An .ico may hold either a PNG or a DIB per size. PNG entries are smaller
    and Explorer reads them happily, but System.Drawing.Icon - which is what
    puts the icon in a window's title bar - only understands DIB, and simply
    throws on the others. So the small sizes are written this way.

    A DIB icon is a BITMAPINFOHEADER whose height is doubled to cover the
    colour bitmap and the 1-bit mask beneath it, with rows stored bottom-up.
    """
    xor = bytearray()
    for y in range(side - 1, -1, -1):
        row = rgba[y * side * 4:(y + 1) * side * 4]
        for x in range(side):
            r, g, b, a = row[x * 4:x * 4 + 4]
            xor += bytes((b, g, r, a))                 # BGRA on disk

    stride = ((side + 31) // 32) * 4                   # mask rows pad to 4 bytes
    mask = bytearray()
    for y in range(side - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(side):
            if rgba[(y * side + x) * 4 + 3] == 0:      # transparent
                bits[x >> 3] |= 0x80 >> (x & 7)
        mask += bits

    header = struct.pack("<IiiHHIIiiII", 40, side, side * 2, 1, 32, 0,
                         len(xor) + len(mask), 0, 0, 0, 0)
    return header + bytes(xor) + bytes(mask)


def _png_bytes(side: int, rgba: bytearray) -> bytes:
    """The same PNG, built in memory - no temp file to leak or lock."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    raw = bytearray()
    for y in range(side):
        raw.append(0)
        raw += rgba[y * side * 4:(y + 1) * side * 4]
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def write_ico(path: Path, side: int, rgba: bytearray,
              sizes=ICO_SIZES) -> Path:
    """A multi-size .ico. Entries are PNG payloads, which Windows accepts."""
    usable = [s for s in sizes if s <= side] or [side]
    # DIB for everything a window actually displays; PNG only at 256, where the
    # format requires it and nothing needs to parse it with System.Drawing.
    images = [(s, _png_bytes(s, resize(side, rgba, s)) if s >= 256
                  else _dib_bytes(s, resize(side, rgba, s)))
              for s in usable]

    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for s, blob in images:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
        blobs += blob
    Path(path).write_bytes(header + entries + blobs)
    return Path(path)


def make(source: Path, dest: Path) -> tuple:
    """Read an image, crop it to a circle, and write a Windows .ico."""
    width, height, rgba = read_png(source)
    side, cropped = circle_crop(width, height, rgba)
    write_ico(Path(dest), side, cropped)
    return side, Path(dest)
