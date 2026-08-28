"""The browser's Downloads folder, which is not ours to tidy freely.

A game arrives twice - where the browser left it, and in the drop folder - so
clearing only the drop folder reclaims half the space. But Downloads belongs to
the person using the machine and is full of things that have nothing to do with
games, so the bar for suggesting a file is higher than for the drop folder.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from esdeck import downloads


class SurveyTests(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.dl = root / "Downloads"
        self.lib = root / "ROMs"
        self.dl.mkdir()
        (self.lib / "snes").mkdir(parents=True)

    def tearDown(self):
        self._dir.cleanup()

    def _offered(self):
        return {c.path.name for c in downloads.survey(self.dl, [self.lib]).found}

    # ------------------------------------------------------------- offered

    def test_a_file_identical_to_one_in_the_library(self):
        (self.lib / "snes" / "Mario.sfc").write_bytes(b"m" * 4000)
        (self.dl / "Mario.sfc").write_bytes(b"m" * 4000)
        self.assertEqual(self._offered(), {"Mario.sfc"})

    def test_a_browser_duplicate_of_it(self):
        # Browsers rename a repeated download "Mario (1).sfc"; it is the same
        # file and just as safe to remove.
        (self.lib / "snes" / "Mario.sfc").write_bytes(b"m" * 4000)
        (self.dl / "Mario (1).sfc").write_bytes(b"m" * 4000)
        self.assertEqual(self._offered(), {"Mario (1).sfc"})

    def test_an_archive_whose_contents_are_all_installed(self):
        # An archive cannot be compared byte for byte with anything, because
        # it was unpacked. What is inside it answers the question instead.
        (self.lib / "snes" / "Mario.sfc").write_bytes(b"m" * 4000)
        (self.lib / "snes" / "Zelda.sfc").write_bytes(b"z" * 4000)
        with zipfile.ZipFile(self.dl / "Pack.zip", "w") as zf:
            zf.writestr("Mario.sfc", "m" * 4000)
            zf.writestr("Zelda.sfc", "z" * 4000)
        self.assertEqual(self._offered(), {"Pack.zip"})

    def test_artwork_inside_an_archive_does_not_count_against_it(self):
        # esdeck deliberately never files artwork, so an archive full of box
        # art would otherwise never look installed.
        (self.lib / "snes" / "Mario.sfc").write_bytes(b"m" * 4000)
        with zipfile.ZipFile(self.dl / "Pack.zip", "w") as zf:
            zf.writestr("Mario.sfc", "m" * 4000)
            zf.writestr("Mario-image.png", "art")
            zf.writestr("box.jpg", "art")
        self.assertEqual(self._offered(), {"Pack.zip"})

    # ------------------------------------------------------------ left alone

    def test_an_archive_that_was_never_sorted(self):
        with zipfile.ZipFile(self.dl / "New.zip", "w") as zf:
            zf.writestr("Contra.nes", "c" * 4000)
        self.assertEqual(self._offered(), set())

    def test_a_half_installed_archive(self):
        (self.lib / "snes" / "A.sfc").write_bytes(b"a" * 10)
        with zipfile.ZipFile(self.dl / "Half.zip", "w") as zf:
            for name in ("A.sfc", "B.sfc", "C.sfc", "D.sfc"):
                zf.writestr(name, "x" * 10)
        self.assertEqual(self._offered(), set())

    def test_same_name_but_different_contents(self):
        (self.lib / "snes" / "Zelda.sfc").write_bytes(b"z" * 4000)
        (self.dl / "Zelda.sfc").write_bytes(b"COMPLETELY DIFFERENT" * 20)
        self.assertEqual(self._offered(), set())

    def test_someones_own_files(self):
        (self.lib / "snes" / "Mario.sfc").write_bytes(b"m" * 4000)
        (self.dl / "tax-return-2026.pdf").write_bytes(b"private" * 100)
        (self.dl / "cv.docx").write_bytes(b"private" * 100)
        (self.dl / "installer.exe").write_bytes(b"MZ" + b"x" * 4000)
        self.assertEqual(self._offered(), set())

    def test_it_counts_what_it_left_alone(self):
        (self.dl / "a.pdf").write_bytes(b"x" * 50)
        (self.dl / "b.pdf").write_bytes(b"y" * 50)
        report = downloads.survey(self.dl, [self.lib])
        self.assertEqual(report.found, [])
        self.assertEqual(report.skipped_unmatched, 2)

    def test_a_missing_downloads_folder_is_not_an_error(self):
        report = downloads.survey(Path(self._dir.name) / "nope", [self.lib])
        self.assertEqual(report.found, [])
        self.assertEqual(report.reclaimable, 0)


class FolderTests(unittest.TestCase):

    def test_it_finds_a_real_downloads_folder(self):
        # Asked of Windows rather than assumed: it can be moved, and OneDrive
        # moves it without asking.
        found = downloads.folder()
        if found is None:
            self.skipTest("no Downloads folder on this machine")
        self.assertTrue(found.is_dir())


class DropFolderArchiveTests(unittest.TestCase):
    """The drop folder has to answer the same question the same way.

    An archive is unpacked on the way in, so nothing in the library is ever
    identical to it. Comparing content never matched one, and every archive in
    the drop folder was reported "not in the library" and kept - while the
    identical download was correctly identified as installed and removed. The
    same file, two opposite answers, in one run.
    """

    def setUp(self):
        from esdeck import clean
        self.clean = clean
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.inc = root / "Incoming"
        self.lib = root / "ROMs"
        self.inc.mkdir()
        (self.lib / "3ds").mkdir(parents=True)

    def tearDown(self):
        self._dir.cleanup()

    def _safe(self):
        report = self.clean.survey([self.inc], [self.lib])
        return {c.source.name for c in report.safe}

    def test_an_unpacked_archive_is_recognised(self):
        (self.lib / "3ds" / "Omega Ruby.3ds").write_bytes(b"r" * 9000)
        with zipfile.ZipFile(self.inc / "Omega Ruby (USA).zip", "w") as zf:
            zf.writestr("Omega Ruby.3ds", "r" * 9000)
        self.assertEqual(self._safe(), {"Omega Ruby (USA).zip"})

    def test_it_says_why(self):
        (self.lib / "3ds" / "A.3ds").write_bytes(b"a" * 900)
        with zipfile.ZipFile(self.inc / "Pack.zip", "w") as zf:
            zf.writestr("A.3ds", "a" * 900)
        report = self.clean.survey([self.inc], [self.lib])
        self.assertIn("inside", report.safe[0].reason)

    def test_an_archive_that_was_never_sorted_is_kept(self):
        with zipfile.ZipFile(self.inc / "New.zip", "w") as zf:
            zf.writestr("Contra.nes", "c" * 900)
        self.assertEqual(self._safe(), set())
        self.assertEqual(len(self.clean.survey([self.inc], [self.lib]).unmatched), 1)

    def test_a_half_installed_archive_is_kept(self):
        (self.lib / "3ds" / "A.3ds").write_bytes(b"a" * 10)
        with zipfile.ZipFile(self.inc / "Half.zip", "w") as zf:
            for name in ("A.3ds", "B.3ds", "C.3ds", "D.3ds"):
                zf.writestr(name, "x" * 10)
        self.assertEqual(self._safe(), set())

    def test_a_split_volume_is_left_for_its_first_part(self):
        (self.inc / "Set.part02.rar").write_bytes(b"x" * 500)
        report = self.clean.survey([self.inc], [self.lib])
        self.assertEqual(report.safe, [])
        self.assertEqual(report.unmatched[0].reason, "part of a split archive")

    def test_a_plain_file_still_needs_its_bytes_to_match(self):
        (self.lib / "3ds" / "Game.3ds").write_bytes(b"g" * 900)
        (self.inc / "Game.3ds").write_bytes(b"DIFFERENT" * 100)
        self.assertEqual(self._safe(), set())
