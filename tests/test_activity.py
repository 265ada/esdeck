"""Scraped artwork, stale ES-DE state, and the progress display."""

import io
import contextlib
import tempfile
import time
import unittest
from pathlib import Path

from esdeck import cleanup, progress


class ScraperNameTests(unittest.TestCase):
    """Name alone identifies scraper output, whatever it is wearing.

    The screen that prompted this showed a PICO-8 system listing "007 - The
    World Is Not Enough-image" and forty more like it. Every one was artwork.
    """

    def test_image_suffix_is_artwork(self):
        for name in ("007 - The World Is Not Enough-image.png",
                     "A, Bug's Life-image.jpg",
                     "Aidyn Chronicles - The First Mage-image.png",
                     "Sonic-marquee.png", "Zelda-titlescreen.jpg",
                     "Mario-video.mp4", "Doom-manual.pdf"):
            self.assertTrue(cleanup.scraper_name(name), name)

    def test_real_games_are_not(self):
        for name in ("Sonic (USA).md", "Celeste.p8.png", "Doom.wad",
                     "Some-imagery Game.md", "image.png"):
            self.assertFalse(cleanup.scraper_name(name), name)

    def test_scraper_named_png_is_never_spared_as_a_cartridge(self):
        with tempfile.TemporaryDirectory() as td:
            rom = Path(td) / "ROMs" / "pico8"
            rom.mkdir(parents=True)
            # A file that would pass the cartridge test on content, but is
            # plainly named as scraper output.
            (rom / "007 - The World Is Not Enough-image.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"pico-8 cartridge" * 8)
            report = cleanup.find_junk(Path(td) / "ROMs")
            self.assertEqual(len(report.junk), 1)
            self.assertEqual(report.kept, [])
            self.assertEqual(report.junk[0].reason, "scraped artwork")

    def test_a_genuine_cartridge_is_still_kept(self):
        with tempfile.TemporaryDirectory() as td:
            rom = Path(td) / "ROMs" / "pico8"
            rom.mkdir(parents=True)
            (rom / "Celeste.p8.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"made with pico-8" * 8)
            report = cleanup.find_junk(Path(td) / "ROMs")
            self.assertEqual(report.junk, [])
            self.assertEqual(len(report.kept), 1)


class StaleEsDeStateTests(unittest.TestCase):
    """Removing the files is not enough on its own.

    ES-DE keeps a gamelist per system and will go on listing what it claims,
    which is how a system survives having every one of its games deleted.
    """

    def _tree(self, td):
        es, rom = Path(td) / "ES-DE", Path(td) / "ROMs"
        (es / "gamelists" / "pico8").mkdir(parents=True)
        (es / "gamelists" / "pico8" / "gamelist.xml").write_text("<x/>" * 100)
        (es / "gamelists" / "snes").mkdir(parents=True)
        (es / "gamelists" / "snes" / "gamelist.xml").write_text("<x/>")
        (es / "downloaded_media" / "pico8").mkdir(parents=True)
        (es / "downloaded_media" / "pico8" / "a-image.png").write_bytes(b"x" * 500)
        (rom / "snes").mkdir(parents=True)
        (rom / "snes" / "Mario.sfc").write_bytes(b"rom")
        (rom / "pico8").mkdir(parents=True)          # emptied by a clean
        return es, rom

    def test_finds_the_gamelist_of_an_emptied_system(self):
        with tempfile.TemporaryDirectory() as td:
            es, rom = self._tree(td)
            names = [d.name for d in cleanup.stale_gamelists(es, rom)]
            self.assertEqual(names, ["pico8"])

    def test_leaves_a_system_that_still_has_games(self):
        with tempfile.TemporaryDirectory() as td:
            es, rom = self._tree(td)
            self.assertNotIn("snes", [d.name for d in cleanup.stale_gamelists(es, rom)])
            self.assertNotIn("snes", [d.name for d in cleanup.stale_media(es, rom)])

    def test_finds_orphaned_scraped_media(self):
        with tempfile.TemporaryDirectory() as td:
            es, rom = self._tree(td)
            names = [d.name for d in cleanup.stale_media(es, rom)]
            self.assertEqual(names, ["pico8"])

    def test_remove_tree_reports_bytes_and_only_deletes_when_told(self):
        with tempfile.TemporaryDirectory() as td:
            es, rom = self._tree(td)
            target = cleanup.stale_media(es, rom)[0]
            freed = cleanup.remove_tree(target, dry_run=True)
            self.assertEqual(freed, 500)
            self.assertTrue(target.is_dir())
            cleanup.remove_tree(target, dry_run=False)
            self.assertFalse(target.is_dir())


class ProgressDisplayTests(unittest.TestCase):

    def test_estimate_follows_a_change_of_pace(self):
        bar = progress.Progress(total_bytes=1000)
        bar.started = time.monotonic() - 20          # a slow start
        bar._mark_at = time.monotonic() - 1.0
        bar._mark_bytes = 0
        bar.bytes_done = 500                          # then 500 B in one second
        bar.draw(force=True)
        # Scaling elapsed by the fraction done would say 20s; the recent rate
        # says about one, which is what is actually going to happen.
        self.assertLess(bar.eta, 3)

    def test_the_display_keeps_ticking_while_nothing_happens(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with progress.Progress(total_bytes=1000).start(every=0.4) as bar:
                bar.advance(nbytes=100, label="hashing")
                time.sleep(1.6)
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 3)
        self.assertGreater(len({l.strip()[0] for l in lines}), 1)   # spinner turns

    def test_disk_readout_waits_for_a_job_worth_measuring(self):
        bar = progress.Progress(total_bytes=100)
        bar.advance(nbytes=10)
        self.assertNotIn("disk", bar.line())
        bar.started = time.monotonic() - (progress.DISK_AFTER + 5)
        self.assertIn("disk", bar.line())


class MissingLibraryTests(unittest.TestCase):
    """An absent library must never be mistaken for an emptied one.

    Every "is this system dead?" test answers yes when the drive is not there,
    so without a guard a wrong path would delete every gamelist and all the
    scraped artwork for a collection that is entirely fine.
    """

    def _es(self, td):
        es = Path(td) / "ES-DE"
        (es / "gamelists" / "snes").mkdir(parents=True)
        (es / "gamelists" / "snes" / "gamelist.xml").write_text("<x/>")
        (es / "downloaded_media" / "snes").mkdir(parents=True)
        (es / "downloaded_media" / "snes" / "a-image.png").write_bytes(b"x")
        return es

    def test_nothing_is_stale_when_the_drive_is_not_there(self):
        with tempfile.TemporaryDirectory() as td:
            es = self._es(td)
            gone = Path(td) / "no-such-drive" / "ROMs"
            self.assertEqual(cleanup.stale_gamelists(es, gone), [])
            self.assertEqual(cleanup.stale_media(es, gone), [])

    def test_nothing_is_stale_when_the_library_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            es = self._es(td)
            rom = Path(td) / "ROMs"
            (rom / "snes").mkdir(parents=True)          # folder, but no games
            self.assertFalse(cleanup.library_is_intact(rom))
            self.assertEqual(cleanup.stale_gamelists(es, rom), [])
            self.assertEqual(cleanup.stale_media(es, rom), [])

    def test_a_populated_library_is_recognised(self):
        with tempfile.TemporaryDirectory() as td:
            rom = Path(td) / "ROMs"
            (rom / "snes").mkdir(parents=True)
            (rom / "snes" / "Mario.sfc").write_bytes(b"rom")
            self.assertTrue(cleanup.library_is_intact(rom))
