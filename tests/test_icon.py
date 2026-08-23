"""The .ico we generate has to be readable by Windows itself."""

import struct
import tempfile
import unittest
from pathlib import Path

from esdeck import icon


class TitleBarIconTests(unittest.TestCase):
    """The small sizes must be DIB, not PNG.

    System.Drawing.Icon puts the icon in a window's title bar, and it throws on
    PNG-compressed entries rather than falling back. An .ico of pure PNG looked
    right in Explorer and left the app showing the default WinForms icon.
    """

    def _ico(self):
        rgba = bytearray([200, 100, 50, 255] * (64 * 64))
        side, cropped = icon.circle_crop(64, 64, rgba)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "x.ico"
            icon.write_ico(dest, side, cropped)
            return dest.read_bytes()

    def _entries(self, data):
        count = struct.unpack("<H", data[4:6])[0]
        out = []
        for i in range(count):
            dim, _, _, _, _, _bpp, size, off = struct.unpack(
                "<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            out.append((dim or 256, data[off:off + size]))
        return out

    def test_small_sizes_are_dib(self):
        for dim, blob in self._entries(self._ico()):
            if dim < 256:
                self.assertFalse(blob.startswith(b"\x89PNG"),
                                 f"{dim}px entry is PNG; Windows cannot show it")
                self.assertEqual(struct.unpack("<I", blob[:4])[0], 40,
                                 f"{dim}px entry is not a BITMAPINFOHEADER")

    def test_dib_height_is_doubled_for_the_mask(self):
        blob = dict(self._entries(self._ico()))[32]
        width, height = struct.unpack("<ii", blob[4:12])
        self.assertEqual((width, height), (32, 64))

    def test_dib_is_long_enough_for_pixels_and_mask(self):
        blob = dict(self._entries(self._ico()))[16]
        self.assertEqual(len(blob), 40 + 16 * 16 * 4 + 16 * 4)

    def test_transparent_corner_is_set_in_the_mask(self):
        side = 32
        blob = dict(self._entries(self._ico()))[side]
        stride = ((side + 31) // 32) * 4
        mask = blob[40 + side * side * 4:]
        # Rows are bottom-up, so the last mask row is the top of the image.
        top_row = mask[(side - 1) * stride:side * stride]
        self.assertEqual(top_row[0] & 0x80, 0x80, "corner should be masked out")
