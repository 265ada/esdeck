"""Every run leaves a record, and the records can be handed over as one file."""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from esdeck import logs


class TeeTests(unittest.TestCase):

    def test_writes_to_both_the_console_and_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "a.log"
            with open(dest, "w", encoding="utf-8") as fh:
                import io
                console = io.StringIO()
                tee = logs.Tee(console, fh)
                tee.write("hello\n")
                tee.flush()
                self.assertEqual(console.getvalue(), "hello\n")
            self.assertEqual(dest.read_text(encoding="utf-8"), "hello\n")

    def test_status_lines_become_readable_in_the_file(self):
        # A progress line redraws itself with a carriage return. On screen that
        # is one updating line; in a file it is an unreadable smear.
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "a.log"
            with open(dest, "w", encoding="utf-8") as fh:
                import io
                tee = logs.Tee(io.StringIO(), fh)
                tee.write("\r 10%\r 20%\r 30%")
            self.assertEqual(dest.read_text(encoding="utf-8").count("\n"), 3)


class RecordingTests(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._saved = logs.LOG_DIR
        logs.LOG_DIR = Path(self._dir.name) / "logs"

    def tearDown(self):
        logs.LOG_DIR = self._saved
        self._dir.cleanup()

    def test_a_run_is_recorded_and_restores_the_console(self):
        original = sys.stdout
        restore, path = logs.start("sync --yes")
        try:
            print("filed 3 games")
        finally:
            restore()
        self.assertIs(sys.stdout, original)
        text = path.read_text(encoding="utf-8")
        self.assertIn("esdeck sync --yes", text)
        self.assertIn("filed 3 games", text)
        self.assertIn("finished after", text)

    def test_the_name_says_what_was_run(self):
        restore, path = logs.start("cleanup --yes")
        restore()
        self.assertIn("cleanup---yes", path.name)

    def test_old_logs_are_dropped_but_recent_ones_kept(self):
        logs.LOG_DIR.mkdir(parents=True)
        for i in range(70):
            (logs.LOG_DIR / f"2026-08-{i:02d}_000000_x.log").write_text("x")
        logs.prune(keep=60)
        self.assertEqual(len(logs.entries()), 60)

    def test_export_bundles_every_log_with_a_summary(self):
        for name in ("sync", "cleanup", "doctor"):
            restore, _ = logs.start(name)
            print(f"ran {name}")
            restore()
        with tempfile.TemporaryDirectory() as out:
            path, count, size = logs.export(out)
            self.assertEqual(count, 3)
            self.assertGreater(size, 0)
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                self.assertIn("about.txt", names)
                self.assertEqual(len([n for n in names if n.endswith(".log")]), 3)
                self.assertIn("3 run(s) recorded",
                              zf.read("about.txt").decode("utf-8"))

    def test_logging_never_breaks_the_command(self):
        # An unwritable log directory must not stop the work.
        logs.LOG_DIR = Path("Z:/nowhere/at/all/logs")
        restore, path = logs.start("doctor")
        self.assertIsNone(path)
        restore()


class SelfUpdateTests(unittest.TestCase):
    """The application has to update itself, not only the code it runs.

    Updating replaced the package and left the .exe alone, so the window's own
    behaviour could sit several releases behind the esdeck it was driving. A
    step the application has never heard of is not skipped with a warning - it
    does not exist, and every other step reports success.
    """

    def setUp(self):
        from esdeck import update
        self.update = update
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.exe = self.dir / update.EXE_NAME
        self.exe.write_bytes(b"MZ" + b"the old application" * 200)

    def tearDown(self):
        self._dir.cleanup()

    def _serve(self, payload):
        self.update._get = lambda url, timeout=0, raw=False: payload

    def test_replaces_the_application_and_keeps_the_old_one(self):
        real = self.update._get
        try:
            self._serve(b"MZ" + b"the new application" * 3000)
            self.assertTrue(self.update.refresh_exe(self.dir, log=lambda m: None))
            self.assertIn(b"the new application", self.exe.read_bytes())
            self.assertTrue((self.dir / (self.update.EXE_NAME + ".old")).exists())
        finally:
            self.update._get = real

    def test_refuses_anything_that_is_not_a_program(self):
        # A proxy's error page, or a 404 body, must never be written over the
        # application - that would leave the machine with nothing to run.
        real = self.update._get
        try:
            self._serve(b"<html>404: Not Found</html>" * 2000)
            self.assertFalse(self.update.refresh_exe(self.dir, log=lambda m: None))
            self.assertIn(b"the old application", self.exe.read_bytes())
        finally:
            self.update._get = real

    def test_refuses_a_suspiciously_small_download(self):
        real = self.update._get
        try:
            self._serve(b"MZ" + b"x" * 50)
            self.assertFalse(self.update.refresh_exe(self.dir, log=lambda m: None))
            self.assertIn(b"the old application", self.exe.read_bytes())
        finally:
            self.update._get = real

    def test_does_nothing_when_already_current(self):
        real = self.update._get
        try:
            self._serve(self.exe.read_bytes())
            self.assertFalse(self.update.refresh_exe(self.dir, log=lambda m: None))
            self.assertFalse((self.dir / (self.update.EXE_NAME + ".old")).exists())
        finally:
            self.update._get = real

    def test_says_nothing_when_not_running_beside_an_exe(self):
        self.exe.unlink()
        self.assertFalse(self.update.refresh_exe(self.dir, log=lambda m: None))
