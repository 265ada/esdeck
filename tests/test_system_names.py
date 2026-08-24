"""The folder a game is filed into has to be the name ES-DE looks for.

ES-DE finds a system by the exact name of its folder under the ROM directory.
Nintendo GameCube is "gc" - file it under "gamecube" and ES-DE simply does not
see it, with no error to explain why. The same trap exists for every system
whose common name differs from its folder name, so this pins the ones most
easily got wrong and checks the whole set against ES-DE when it is installed.
"""

import unittest

from esdeck import config, sniff, systems

#: Folder name on the left, what someone would reasonably have typed instead.
#: Every one of these would silently fail to appear in ES-DE.
ES_DE_FOLDER_NAMES = {
    "gc": "gamecube",
    "psx": "ps1",
    "megadrive": "genesis",
    "pcengine": "turbografx16",
    "n64": "nintendo64",
    "gb": "gameboy",
    "gbc": "gameboycolor",
    "gba": "gameboyadvance",
    "nds": "ds",
    "mastersystem": "sms",
    "atari2600": "vcs",
}


class FolderNameTests(unittest.TestCase):

    def test_the_awkward_ones_use_the_name_es_de_looks_for(self):
        for wanted, mistake in ES_DE_FOLDER_NAMES.items():
            self.assertIn(wanted, systems.BY_KEY,
                          f"ES-DE looks for {wanted!r} and esdeck does not use it")
            self.assertNotIn(mistake, systems.BY_KEY,
                             f"{mistake!r} is not a folder ES-DE detects")

    def test_gamecube_is_gc(self):
        # Called out on its own because it is the one that bit us.
        self.assertIn("gc", systems.BY_KEY)
        self.assertIn(".gcm", systems.BY_KEY["gc"].exts)

    def test_gamecube_answers_to_its_other_names_on_the_way_in(self):
        # A drop folder called "GameCube" should still be understood; it is
        # only the folder we file into that has to be "gc".
        self.assertIn("gamecube", systems.BY_KEY["gc"].aliases)

    def test_iso_is_not_claimed_by_extension(self):
        # .iso belongs to GameCube, Wii, PS2, Saturn and more, so claiming it
        # by extension would file half of them wrongly. It is decided by
        # reading the disc header instead - see DiscSignatureTests.
        self.assertNotIn(".iso", systems.BY_KEY["gc"].exts)


class AgainstEsDeTests(unittest.TestCase):
    """When ES-DE is installed, check the whole set rather than a sample."""

    def setUp(self):
        from esdeck import esde
        try:
            self.known = set(esde.load(config.load().es_config_dir))
        except Exception:
            self.known = set()
        if not self.known:
            self.skipTest("ES-DE is not installed here")

    def test_every_folder_we_sort_into_is_one_es_de_detects(self):
        unknown = sorted(set(systems.BY_KEY) - self.known)
        self.assertEqual(unknown, [],
                         "games filed here would never appear in ES-DE")


class DiscSignatureTests(unittest.TestCase):
    """A GameCube and a Wii disc are both a bare .iso; only the header differs."""

    def _disc(self, tmp, name, offset, magic):
        head = bytearray(0x100)
        head[offset:offset + 4] = bytes.fromhex(magic)
        path = tmp / name
        path.write_bytes(bytes(head) + b"\0" * 4096)
        return path

    def test_gamecube_and_wii_are_told_apart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            gc = self._disc(td, "Melee.iso", 0x1C, "C2339F3D")
            wii = self._disc(td, "Sports.iso", 0x18, "5D1C9EA3")
            self.assertEqual(sniff.identify(gc), "gc")
            self.assertEqual(sniff.identify(wii), "wii")
