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
