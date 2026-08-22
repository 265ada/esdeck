"""Tests for esdeck. Run: python -m unittest discover -s tests"""

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from esdeck import apply as apply_mod          # noqa: E402
from esdeck import config, plan, readme_parse, scan, systems  # noqa: E402


def touch(p: Path, size: int = 64) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0" * size)
    return p


class TestSystems(unittest.TestCase):
    def test_unambiguous_extension(self):
        self.assertEqual(systems.systems_for_ext(".sfc"), ["snes"])

    def test_ambiguous_extension_lists_candidates(self):
        self.assertIn("ps2", systems.systems_for_ext(".iso"))
        self.assertGreater(len(systems.systems_for_ext(".iso")), 1)

    def test_hint_from_folder_name(self):
        self.assertEqual(systems.system_from_hint("PSX Games"), "psx")
        self.assertEqual(systems.system_from_hint("Sony PlayStation 2"), "ps2")
        self.assertIsNone(systems.system_from_hint("Assorted Downloads"))

    def test_doc_detection(self):
        self.assertTrue(systems.is_doc("README.txt"))
        self.assertTrue(systems.is_doc("READ ME FIRST.TXT"))
        self.assertTrue(systems.is_doc("install-notes.md"))
        self.assertFalse(systems.is_doc("game.iso"))
        self.assertFalse(systems.is_doc("readme.iso"))


class TestReadmeParse(unittest.TestCase):
    TEXT = (
        "Cool Game\n"
        "1. Mount CD1.iso with Daemon Tools.\n"
        "2. Run setup.exe and enter your serial.\n"
        "Requires PCSX2 and bios scph39001.bin.\n"
        'setup.exe /SILENT /DIR="C:\\Games"\n'
        "Disc 2 holds the ending.\n"
    )

    def setUp(self):
        self.h = readme_parse.parse(self.TEXT, "README.txt")

    def test_title_and_steps(self):
        self.assertEqual(self.h.title, "Cool Game")
        self.assertEqual(len(self.h.steps), 2)

    def test_prose_is_not_a_command(self):
        """'2. Run setup.exe' is a step, not something to execute."""
        self.assertEqual([c["text"] for c in self.h.commands],
                         ['setup.exe /SILENT /DIR="C:\\Games"'])

    def test_emulator_and_system(self):
        self.assertIn("pcsx2", self.h.emulators)
        self.assertIn("ps2", self.h.systems)

    def test_bios_only_from_bios_context(self):
        self.assertEqual(self.h.bios, ["scph39001.bin"])

    def test_flags(self):
        self.assertIn("needs_mount", self.h.flags)
        self.assertIn("needs_serial", self.h.flags)

    def test_disc_count(self):
        self.assertEqual(self.h.discs, 2)

    def test_patch_command_filenames_are_not_bios(self):
        h = readme_parse.parse("Apply xdelta3 -d -s game.bin patch.xdelta out.bin\n")
        self.assertEqual(h.bios, [])
        self.assertIn("needs_patch", h.flags)

    def test_latin1_readme_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "readme.txt"
            p.write_bytes("Jos\xe9's Game\n1. Install it.\n".encode("cp1252"))
            h = readme_parse.parse(readme_parse.read_text(p), "readme.txt")
            self.assertTrue(h.steps)


class ScanFixture(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.src = Path(self.td.name) / "incoming"
        self.roms = Path(self.td.name) / "ROMs"
        self.roms.mkdir(parents=True)
        self.cfg = config.Config(rom_dir=str(self.roms),
                                 install_dir=str(self.roms / "windows"))

    def tearDown(self):
        self.td.cleanup()

    def items(self):
        return {i.name: i for i in scan.scan(self.src)}


class TestScan(ScanFixture):
    def test_loose_roms_in_a_system_folder_split_into_games(self):
        touch(self.src / "SNES Games" / "Super Mario World (USA).sfc")
        touch(self.src / "SNES Games" / "Chrono Trigger (USA) [!].smc")
        items = self.items()
        self.assertEqual(set(items), {"Super Mario World", "Chrono Trigger"})
        self.assertTrue(all(i.system == "snes" and i.confidence == "high"
                            for i in items.values()))

    def test_multifile_disc_set_stays_one_game(self):
        for d in (1, 2):
            touch(self.src / "FF7" / f"FF7 (Disc {d}).bin")
            touch(self.src / "FF7" / f"FF7 (Disc {d}).cue")
        (self.src / "FF7" / "README.txt").write_text("Use DuckStation for this psx game.\n")
        items = self.items()
        self.assertEqual(list(items), ["FF7"])
        self.assertEqual(items["FF7"].system, "psx")

    def test_installer_without_rom_is_a_windows_game(self):
        touch(self.src / "Retro Racer" / "setup.exe")
        item = self.items()["Retro Racer"]
        self.assertEqual(item.system, "windows")

    def test_ambiguous_iso_is_unresolved_not_guessed(self):
        touch(self.src / "Mystery.iso")
        item = self.items()["Mystery"]
        self.assertIsNone(item.system)
        self.assertIn("ps2", item.candidates)

    def test_readme_absent_still_detects(self):
        touch(self.src / "Zelda (USA).n64")
        self.assertEqual(self.items()["Zelda"].system, "n64")

    def test_clean_title_strips_region_tags(self):
        self.assertEqual(scan.clean_title("Some.Game (USA) [!].zip"), "Some Game")


class TestPlan(ScanFixture):
    def test_arcade_zip_is_copied_not_extracted(self):
        d = self.src / "Arcade"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "sf2ce.zip", "w") as z:
            z.writestr("sf2ce.01", "x")
        item = self.items()["sf2ce"]
        actions = plan.build(item, self.cfg)["actions"]
        self.assertTrue(any(a["type"] == "copy" for a in actions))
        self.assertFalse(any(a["type"] == "extract" for a in actions))

    def test_multi_disc_gets_m3u(self):
        for d in (1, 2, 3):
            touch(self.src / "FF7" / f"FF7 (Disc {d}).bin")
            (self.src / "FF7" / f"FF7 (Disc {d}).cue").write_text("FILE\n")
        (self.src / "FF7" / "README.txt").write_text("psx game, use DuckStation\n")
        pl = plan.build(self.items()["FF7"], self.cfg)
        m3u = [a for a in pl["actions"] if a["type"] == "m3u"]
        self.assertEqual(len(m3u), 1)
        self.assertEqual(m3u[0]["entries"],
                         ["FF7 (Disc 1).cue", "FF7 (Disc 2).cue", "FF7 (Disc 3).cue"])

    def test_readme_command_becomes_review_only_action(self):
        touch(self.src / "Racer" / "setup.exe")
        (self.src / "Racer" / "README.txt").write_text(
            "Racer\nsetup.exe /SILENT\nEnter the serial when asked.\n")
        pl = plan.build(self.items()["Racer"], self.cfg)
        cmds = [a for a in pl["actions"] if a["type"] == "suggested_command"]
        self.assertEqual(len(cmds), 1)
        self.assertTrue(cmds[0]["needs_review"])

    def test_installer_action_always_needs_review(self):
        touch(self.src / "Racer" / "setup.exe")
        pl = plan.build(self.items()["Racer"], self.cfg)
        installs = [a for a in pl["actions"] if a["type"] == "install"]
        self.assertTrue(installs and all(a["needs_review"] for a in installs))

    def test_unknown_system_warns(self):
        touch(self.src / "Mystery.iso")
        pl = plan.build(self.items()["Mystery"], self.cfg)
        self.assertTrue(any("could not be determined" in w for w in pl["warnings"]))


class TestApply(ScanFixture):
    def _plan_for(self, name):
        return plan.build(self.items()[name], self.cfg)

    def test_dry_run_writes_nothing(self):
        touch(self.src / "Zelda (USA).n64")
        apply_mod.apply_plan(self._plan_for("Zelda"), dry_run=True,
                             roots=[str(self.roms)], log=lambda *a: None)
        self.assertFalse((self.roms / "n64").exists())

    def test_apply_copies_rom(self):
        touch(self.src / "Zelda (USA).n64")
        res = apply_mod.apply_plan(self._plan_for("Zelda"), dry_run=False,
                                   roots=[str(self.roms)], log=lambda *a: None)
        self.assertEqual(res.errors, [])
        self.assertTrue((self.roms / "n64" / "Zelda (USA).n64").is_file())

    def test_never_runs_review_actions(self):
        touch(self.src / "Racer" / "setup.exe")
        (self.src / "Racer" / "README.txt").write_text("Racer\nsetup.exe /SILENT\n")
        res = apply_mod.apply_plan(self._plan_for("Racer"), dry_run=False,
                                   roots=[str(self.roms)], log=lambda *a: None)
        self.assertTrue(any("install" in s for s in res.skipped))
        self.assertTrue(any("suggested_command" in s for s in res.skipped))

    def test_refuses_to_write_outside_roots(self):
        pl = {"actions": [{"type": "copy", "src": "x",
                           "dst": str(Path(self.td.name) / "elsewhere" / "evil.exe")}]}
        res = apply_mod.apply_plan(pl, dry_run=False, roots=[str(self.roms)],
                                   log=lambda *a: None)
        self.assertTrue(res.errors and "refusing to write outside" in res.errors[0])

    def test_zip_slip_is_blocked(self):
        z = self.roms / "bad.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../../escaped.txt", "pwned")
        dest = self.roms / "out"
        pl = {"actions": [{"type": "extract", "src": str(z), "dst": str(dest)}]}
        res = apply_mod.apply_plan(pl, dry_run=False, roots=[str(self.roms)],
                                   log=lambda *a: None)
        self.assertTrue(res.errors and "unsafe path" in res.errors[0])
        self.assertFalse((Path(self.td.name) / "escaped.txt").exists())

    def test_existing_file_not_overwritten_by_default(self):
        touch(self.src / "Zelda (USA).n64")
        (self.roms / "n64").mkdir(parents=True)
        target = self.roms / "n64" / "Zelda (USA).n64"
        target.write_bytes(b"original")
        apply_mod.apply_plan(self._plan_for("Zelda"), dry_run=False,
                             roots=[str(self.roms)], log=lambda *a: None)
        self.assertEqual(target.read_bytes(), b"original")


class TestConfigProfile(unittest.TestCase):
    def test_profile_excludes_machine_paths(self):
        cfg = config.Config(rom_dir=r"D:\ROMs", install_dir=r"D:\Games", auto_extract=False)
        prof = config.profile_from(cfg)
        self.assertNotIn("rom_dir", prof)
        self.assertIn("auto_extract", prof)

    def test_import_profile_keeps_local_paths(self):
        cfg = config.Config(rom_dir=r"E:\ROMs", auto_extract=True)
        merged = config.apply_profile(cfg, {"auto_extract": False, "rom_dir": r"D:\ROMs"})
        self.assertEqual(merged.rom_dir, r"E:\ROMs")
        self.assertFalse(merged.auto_extract)

    def test_read_es_settings(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "settings"
            d.mkdir()
            (d / "es_settings.xml").write_text(
                '<?xml version="1.0"?>\n<string name="ROMDirectory" value="D:\\ROMs" />\n'
                '<bool name="VSync" value="true" />\n', encoding="utf-8")
            got = config.read_es_settings(Path(td))
            self.assertEqual(got["ROMDirectory"], "D:\\ROMs")
            self.assertEqual(got["VSync"], "true")


class TestCLI(ScanFixture):
    def test_plan_then_apply_roundtrip(self):
        os.environ["ESDECK_HOME"] = str(Path(self.td.name) / "home")
        from importlib import reload
        reload(config)
        from esdeck import cli
        reload(cli)
        touch(self.src / "Zelda (USA).n64")
        self.assertEqual(cli.main(["init", "--rom-dir", str(self.roms)]), 0)
        out = str(Path(self.td.name) / "plan.json")
        self.assertEqual(cli.main(["plan", str(self.src), "--out", out]), 0)
        bundle = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(bundle["plans"][0]["system"], "n64")
        self.assertEqual(cli.main(["apply", out, "--yes"]), 0)
        self.assertTrue((self.roms / "n64" / "Zelda (USA).n64").is_file())


if __name__ == "__main__":
    unittest.main()
