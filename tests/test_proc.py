"""Child processes must not conjure console windows.

The desktop application has no console. On Windows a console program started
from a process without one is given a brand new console window - which is why
7-Zip, winget and pip flashed windows over whatever you were doing, and why one
of them could be closed mid-extraction by a stray click.
"""

import subprocess
import unittest
from pathlib import Path

from esdeck import proc

SOURCES = sorted(Path(__file__).resolve().parent.parent.joinpath("esdeck").glob("*.py"))


class NoWindowTests(unittest.TestCase):

    def test_every_call_site_goes_through_the_helper(self):
        offenders = []
        for path in SOURCES:
            if path.name == "proc.py":
                continue
            text = path.read_text(encoding="utf-8")
            for call in ("subprocess.run(", "subprocess.Popen("):
                if call in text:
                    offenders.append(f"{path.name}: {call}")
        self.assertEqual(offenders, [],
                         "these bypass proc.run and will open a console window")

    def test_the_flag_is_applied(self):
        seen = {}

        def fake(cmd, **kwargs):
            seen.update(kwargs)
            return "result"

        real, subprocess.run = subprocess.run, fake
        try:
            self.assertEqual(proc.run(["x"]), "result")
        finally:
            subprocess.run = real
        if proc.CREATE_NO_WINDOW:
            self.assertEqual(seen.get("creationflags"), proc.CREATE_NO_WINDOW)

    def test_an_explicit_choice_is_respected(self):
        seen = {}

        def fake(cmd, **kwargs):
            seen.update(kwargs)

        real, subprocess.run = subprocess.run, fake
        try:
            proc.run(["x"], creationflags=0)
        finally:
            subprocess.run = real
        self.assertEqual(seen.get("creationflags"), 0)
