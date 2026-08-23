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
from esdeck import archives, bios, clean, cleanup, config, controller  # noqa: E402
from esdeck import cores, drives  # noqa: E402
from esdeck import dedupe, emulators, esde, history  # noqa: E402
from esdeck import progress  # noqa: E402
from esdeck import launcher, plan  # noqa: E402
from esdeck import readme_parse  # noqa: E402
from esdeck import patch, scan, tidy  # noqa: E402
from esdeck import sniff  # noqa: E402
from esdeck import systems  # noqa: E402


def touch(p: Path, size: int = 64) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0" * size)
    return p


class TestSystems(unittest.TestCase):
    def test_unambiguous_extension(self):
        self.assertEqual(systems.systems_for_ext(".sfc"), ["snes"])

    def test_curated_table_beats_es_de_looseness(self):
        """ES-DE lists .sfc under gb and gbc too; SNES ROMs must still resolve."""
        self.assertEqual(systems.systems_for_ext(".sfc")[0], "snes")
        self.assertEqual(systems.systems_for_ext(".n64")[0], "n64")

    def test_genuinely_ambiguous_extensions_flagged(self):
        self.assertTrue(systems.is_genuinely_ambiguous(".iso"))
        self.assertTrue(systems.is_genuinely_ambiguous(".wad"))
        self.assertFalse(systems.is_genuinely_ambiguous(".n64"))

    def test_tie_break_prefers_common_system(self):
        """ES-DE has both 'doom' and 'dos'; alphabetical order must not decide."""
        self.assertEqual(systems.rank_candidates(["doom", "dos"])[0], "dos")

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
        # The playlist sits in the system folder and points into the game's
        # subfolder, which is hidden so ES-DE lists the .m3u only.
        self.assertEqual(Path(m3u[0]["path"]).parent, self.roms / "psx")
        self.assertEqual(m3u[0]["entries"],
                         ["FF7/FF7 (Disc 1).cue", "FF7/FF7 (Disc 2).cue",
                          "FF7/FF7 (Disc 3).cue"])
        hides = [a for a in pl["actions"] if a["type"] == "hide"]
        self.assertEqual([Path(a["path"]).name for a in hides], ["FF7"])

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

    def test_zip_slip_cannot_escape_the_destination(self):
        """An archive with ../ paths must not write outside the target folder.

        7-Zip strips the traversal itself (verified), and the stdlib fallback
        raises. Either way the file must stay inside dest.
        """
        z = self.roms / "bad.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("../../escaped.txt", "pwned")
        dest = self.roms / "out"
        pl = {"actions": [{"type": "extract", "src": str(z), "dst": str(dest)}]}
        apply_mod.apply_plan(pl, dry_run=False, roots=[str(self.roms)],
                             log=lambda *a: None)
        self.assertFalse((Path(self.td.name) / "escaped.txt").exists())
        self.assertFalse((self.roms / "escaped.txt").exists())

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


class TestLauncher(unittest.TestCase):
    """ES-DE's windows system only sees .bat/.lnk, so folders need a launcher."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.roms = Path(self.td.name) / "ROMs"
        self.install = self.roms / "windows"
        self.game = self.install / "Space Blaster"
        (self.game / "Game Files").mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def test_ignores_installer_and_redist_executables(self):
        touch(self.game / "Game Files" / "game.exe", 5000)
        touch(self.game / "unins000.exe", 9000)
        touch(self.game / "vcredist_x64.exe", 9000)
        found = launcher.find_executables(self.game)
        self.assertEqual([p.name for p in found], ["game.exe"])

    def test_prefers_shallow_and_likely_named(self):
        touch(self.game / "Game Files" / "engine_worker.exe", 9000)
        touch(self.game / "play.exe", 100)
        self.assertEqual(launcher.find_executables(self.game)[0].name, "play.exe")

    def test_writes_bat_that_runs_from_the_game_directory(self):
        exe = touch(self.game / "Game Files" / "game.exe")
        games = launcher.scan_install_dir(self.install, self.roms)
        self.assertEqual(len(games), 1)
        launcher.write_launcher(games[0]["dest"], exe)
        bat = self.install / "Space Blaster.bat"
        self.assertTrue(bat.is_file())
        text = bat.read_text(encoding="utf-8")
        self.assertIn(str(exe.parent), text)
        self.assertIn(str(exe), text)

    def test_existing_launcher_is_not_clobbered(self):
        exe = touch(self.game / "game.exe")
        dest = self.install / "Space Blaster.bat"
        dest.write_text("mine", encoding="utf-8")
        launcher.write_launcher(dest, exe)
        self.assertEqual(dest.read_text(encoding="utf-8"), "mine")

    def test_folder_without_executable_reports_no_candidates(self):
        games = launcher.scan_install_dir(self.install, self.roms)
        self.assertEqual(games[0]["candidates"], [])


class TestEsSettings(unittest.TestCase):
    XML = ('<?xml version="1.0"?>\n'
           '<string name="ROMDirectory" value="" />\n'
           '<string name="MediaDirectory" value="" />\n'
           '<bool name="VSync" value="true" />\n')

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.es = Path(self.td.name) / "ES-DE"
        (self.es / "settings").mkdir(parents=True)
        self.path = self.es / "settings" / "es_settings.xml"
        self.path.write_text(self.XML, encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def test_sets_value_and_leaves_other_lines_alone(self):
        config.write_es_settings(self.es, {"ROMDirectory": r"D:\ROMs"})
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('name="ROMDirectory" value="D:\\ROMs"', text)
        self.assertIn('name="VSync" value="true"', text)
        self.assertEqual(len(text.splitlines()), 4)

    def test_makes_a_backup_once(self):
        config.write_es_settings(self.es, {"ROMDirectory": r"D:\ROMs"})
        backup = self.path.with_suffix(".xml.esdeck-backup")
        self.assertEqual(backup.read_text(encoding="utf-8"), self.XML)
        config.write_es_settings(self.es, {"ROMDirectory": r"E:\Other"})
        self.assertEqual(backup.read_text(encoding="utf-8"), self.XML)

    def test_dry_run_changes_nothing(self):
        changes = config.write_es_settings(self.es, {"ROMDirectory": r"D:\ROMs"},
                                           dry_run=True)
        self.assertTrue(any("ROMDirectory" in c for c in changes))
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.XML)

    def test_unknown_setting_is_reported_not_invented(self):
        changes = config.write_es_settings(self.es, {"NoSuchSetting": "x"})
        self.assertTrue(any("not present" in c for c in changes))
        self.assertNotIn("NoSuchSetting", self.path.read_text(encoding="utf-8"))

    def test_created_file_uses_the_right_element_types(self):
        """ES-DE is typed: ShowHiddenFiles is a <bool>, a <string> is ignored."""
        self.path.unlink()
        config.write_es_settings(self.es, {"ROMDirectory": r"D:\ROMs",
                                           "ShowHiddenFiles": "false"}, create=True)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('<bool name="ShowHiddenFiles" value="false" />', text)
        self.assertIn('<string name="ROMDirectory" value="D:\\ROMs" />', text)

    def test_setting_tag_types(self):
        self.assertEqual(config.setting_tag("ShowHiddenFiles", "false"), "bool")
        self.assertEqual(config.setting_tag("MaxVRAM", "512"), "int")
        self.assertEqual(config.setting_tag("ROMDirectory", r"D:\ROMs"), "string")

    def test_create_writes_a_file_es_de_can_read_back(self):
        self.path.unlink()
        config.write_es_settings(self.es, {"ROMDirectory": r"D:\ROMs",
                                           "ShowHiddenFiles": "false"}, create=True)
        got = config.read_es_settings(self.es)
        self.assertEqual(got["ROMDirectory"], r"D:\ROMs")
        self.assertEqual(got["ShowHiddenFiles"], "false")

    def test_missing_file_raises(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            config.write_es_settings(self.es, {"ROMDirectory": "x"})


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


class TestMessyLayouts(ScanFixture):
    """Shapes that real drop folders actually arrive in."""

    def test_publisher_folder_is_descended_into(self):
        touch(self.src / "Konami Collection" / "Metal Gear Solid" / "MGS.chd")
        touch(self.src / "Konami Collection" / "Castlevania" / "SOTN.chd")
        # Two games one level down, not a single item called 'Konami Collection'.
        self.assertEqual(set(self.items()), {"Metal Gear Solid", "Castlevania"})

    def test_multi_disc_chd_set_is_one_game_not_two(self):
        for d in (1, 2):
            touch(self.src / "Konami" / "Metal Gear Solid" / f"MGS (Disc {d}).chd")
        items = self.items()
        self.assertEqual(list(items), ["Metal Gear Solid"])
        self.assertEqual(len(items["Metal Gear Solid"].files), 2)

    def test_lone_rom_in_system_folder_still_named_after_the_game(self):
        touch(self.src / "SNES" / "Super Mario World (USA).sfc")
        self.assertEqual(list(self.items()), ["Super Mario World"])

    def test_zip_contents_drive_detection(self):
        d = self.src / "Space Blaster.zip"
        d.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(d, "w") as z:
            z.writestr("Game Files/game.exe", "x")
            z.writestr("README.txt", "Space Blaster\n1. Unzip and run game.exe\n")
        item = self.items()["Space Blaster"]
        self.assertEqual(item.system, "windows")

    def test_readme_inside_zip_is_read(self):
        p = self.src / "Archived Game.zip"
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("game.sfc", "x")
            z.writestr("README.txt", "Needs the snes bios nothing.bin\n")
        item = self.items()["Archived Game"]
        self.assertIsNotNone(item.hints)
        self.assertIn("needs_bios", item.hints.flags)

    def test_unopenable_archive_is_reported_not_guessed(self):
        touch(self.src / "Some Game.7z")
        item = self.items()["Some Game"]
        self.assertEqual(item.opaque_archives, ["Some Game.7z"])
        self.assertIsNone(item.system)

    def test_unknown_extension_is_surfaced_not_dropped(self):
        touch(self.src / "weird-game.xyz")
        item = self.items()["weird-game"]
        self.assertTrue(item.unrecognized)

    def test_junk_files_are_ignored(self):
        touch(self.src / "cover.jpg")
        touch(self.src / "filelist.sfv")
        touch(self.src / "Zelda (USA).n64")
        self.assertEqual(list(self.items()), ["Zelda"])

    def test_base_stem_groups_disc_variants(self):
        self.assertEqual(scan.base_stem("MGS (Disc 1)"), scan.base_stem("MGS (Disc 2)"))
        self.assertNotEqual(scan.base_stem("Mario"), scan.base_stem("Zelda"))

    def test_dos_game_folder_is_copied_whole(self):
        """DOOM.EXE is not a recognized ROM extension - copying only ROMs loses it."""
        touch(self.src / "DOOM" / "DOOM.EXE")
        touch(self.src / "DOOM" / "DOOM.WAD")
        (self.src / "DOOM" / "README.TXT").write_text("Run DOOM.EXE in DOSBox.\n")
        pl = plan.build(self.items()["DOOM"], self.cfg)
        trees = [a for a in pl["actions"] if a["type"] == "copy_tree"]
        self.assertEqual(len(trees), 1)
        apply_mod.apply_plan(pl, dry_run=False, roots=[str(self.roms)], log=lambda *a: None)
        for name in ("DOOM.EXE", "DOOM.WAD", "README.TXT"):
            self.assertTrue((self.roms / "dos" / "DOOM" / name).is_file(), name)

    def test_pc_game_in_a_zip_gets_extracted(self):
        p = self.src / "Space Blaster.zip"
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Game Files/game.exe", "x")
        pl = plan.build(self.items()["Space Blaster"], self.cfg)
        self.assertTrue(any(a["type"] == "extract" for a in pl["actions"]))
        apply_mod.apply_plan(pl, dry_run=False,
                             roots=[str(self.roms), str(self.roms / "windows")],
                             log=lambda *a: None)
        self.assertTrue(
            (self.roms / "windows" / "Space Blaster" / "Game Files" / "game.exe").is_file())

    def test_accented_title_survives(self):
        touch(self.src / "Pokémon Édition Rouge (France).gba")
        items = self.items()
        self.assertIn("Pokémon Édition Rouge", items)
        self.assertEqual(items["Pokémon Édition Rouge"].system, "gba")


class TestDiscSniffing(unittest.TestCase):
    """Disc extensions are useless (.cue maps to 73 systems); read the disc."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def _disc(self, name: str, payload: bytes, at: int = 0x9000) -> Path:
        p = self.d / name
        data = bytearray(at + len(payload) + 16)
        data[at:at + len(payload)] = payload
        p.write_bytes(bytes(data))
        return p

    def test_playstation_disc(self):
        p = self._disc("game.bin", b"PLAYSTATION SYSTEM.CNF BOOT=cdrom:SLUS_012.34;1")
        self.assertEqual(sniff.identify(p), "psx")

    def test_playstation_2_told_apart_by_boot2(self):
        p = self._disc("game.iso", b"PLAYSTATION SYSTEM.CNF BOOT2=cdrom0:SLUS_202.02;1")
        self.assertEqual(sniff.identify(p), "ps2")

    def test_saturn_and_dreamcast(self):
        self.assertEqual(sniff.identify(self._disc("s.bin", b"SEGA SEGASATURN ")), "saturn")
        self.assertEqual(sniff.identify(self._disc("d.gdi", b"SEGA SEGAKATANA ")), "dreamcast")

    def test_gamecube_magic_at_offset(self):
        p = self.d / "g.iso"
        data = bytearray(4096)
        data[0x1C:0x20] = bytes([0xC2, 0x33, 0x9F, 0x3D])
        p.write_bytes(bytes(data))
        self.assertEqual(sniff.identify(p), "gc")

    def test_cue_is_followed_to_its_bin(self):
        self._disc("game.bin", b"PLAYSTATION BOOT=cdrom:")
        cue = self.d / "game.cue"
        cue.write_text('FILE "game.bin" BINARY\n  TRACK 01 MODE2/2352\n')
        self.assertEqual(sniff.identify(cue), "psx")

    def test_cue_pointing_at_a_missing_file_is_not_guessed(self):
        cue = self.d / "broken.cue"
        cue.write_text('FILE "nope.bin" BINARY\n')
        self.assertIsNone(sniff.identify(cue))

    def test_unknown_disc_returns_none(self):
        self.assertIsNone(sniff.identify(self._disc("x.bin", b"nothing recognisable")))

    def test_chd_is_left_ambiguous(self):
        """CHD payloads are compressed; guessing would be worse than asking."""
        p = self.d / "game.chd"
        p.write_bytes(b"MComprHD" + bytes(512))
        self.assertIsNone(sniff.identify(p))
        self.assertTrue(sniff.is_chd(p))


class TestMultiDiscFolders(ScanFixture):
    def _psx_disc_folder(self, title: str, disc: int):
        d = self.src / f"{title} (USA) (Disc {disc})"
        d.mkdir(parents=True)
        binf = d / f"{title} (USA) (Disc {disc}).bin"
        data = bytearray(0x9100)
        payload = b"PLAYSTATION BOOT=cdrom:SLUS_012;1  "
        data[0x9000:0x9000 + len(payload)] = payload
        binf.write_bytes(bytes(data))
        (d / f"{title} (USA) (Disc {disc}).cue").write_text(
            'FILE "' + binf.name + '" BINARY\n  TRACK 01 MODE2/2352\n')

    def test_four_disc_folders_become_one_game(self):
        for n in (1, 2, 3, 4):
            self._psx_disc_folder("Legend of Dragoon, The", n)
        items = list(self.items().values())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].system, "psx")
        self.assertEqual(len(items[0].files), 8)

    def test_merged_game_gets_one_m3u_in_disc_order(self):
        for n in (1, 2, 3):
            self._psx_disc_folder("Some RPG", n)
        item = list(self.items().values())[0]
        pl = plan.build(item, self.cfg)
        m3u = [a for a in pl["actions"] if a["type"] == "m3u"]
        self.assertEqual(len(m3u), 1)
        self.assertEqual([e[-12:] for e in m3u[0]["entries"]],
                         ["(Disc 1).cue", "(Disc 2).cue", "(Disc 3).cue"])
        self.assertTrue(all(e.startswith("Some RPG") for e in m3u[0]["entries"]))

    def test_different_games_are_not_merged(self):
        self._psx_disc_folder("Game A", 1)
        self._psx_disc_folder("Game B", 1)
        self.assertEqual(len(self.items()), 2)

    def test_sniffing_beats_an_ambiguous_extension(self):
        """.bin/.cue alone could be six systems; the disc contents decide."""
        self._psx_disc_folder("Solo Game", 1)
        item = list(self.items().values())[0]
        self.assertEqual(item.system, "psx")
        self.assertEqual(item.confidence, "high")


class TestCores(unittest.TestCase):
    """Core names are downloaded by name, so a typo is a silent 404."""

    def test_core_comes_from_es_de_launch_command(self):
        """ES-DE runs the first <command>; installing any other core fails."""
        sysdef = esde.EsSystem("psx", "Sony PlayStation", {".cue"}, [
            ("Beetle PSX",
             r"%EMULATOR_RETROARCH% -L %CORE_RETROARCH%\mednafen_psx_libretro.dll %ROM%"),
            ("SwanStation",
             r"%EMULATOR_RETROARCH% -L %CORE_RETROARCH%\swanstation_libretro.dll %ROM%"),
        ])
        self.assertEqual(sysdef.default_core, "mednafen_psx")

    def test_standalone_emulator_command_has_no_core(self):
        sysdef = esde.EsSystem("ps3", "PS3", set(),
                               [("RPCS3", r"%EMULATOR_RPCS3% --no-gui %ROM%")])
        self.assertIsNone(sysdef.default_core)

    def test_unavailable_cores_are_never_requested(self):
        """Some cores ES-DE names have no Windows build; asking 404s."""
        for core in cores.UNAVAILABLE:
            self.assertNotIn(core, cores.all_cores())

    def test_core_names_look_like_buildbot_names(self):
        for system, core in cores.SYSTEM_CORES.items():
            self.assertIsInstance(core, str, system)
            if core:
                self.assertRegex(core, r"^[a-z0-9_]+$",
                                 f"{system} -> {core!r} is not a buildbot core name")

    def test_all_cores_is_deduplicated_and_drops_blanks(self):
        got = [c for c in cores.all_cores() if c]
        self.assertEqual(len(got), len(set(got)))
        self.assertNotIn("", cores.all_cores() and [c for c in cores.all_cores() if c])

    def test_common_cores_are_all_mapped_somewhere(self):
        mapped = set(cores.SYSTEM_CORES.values())
        for core in cores.COMMON_CORES:
            self.assertIn(core, mapped)

    def test_url_shape(self):
        self.assertTrue(cores.core_url("snes9x").endswith(
            "/snes9x_libretro.dll.zip"))

    def test_cores_needed_only_for_populated_systems(self):
        with tempfile.TemporaryDirectory() as td:
            roms = Path(td)
            (roms / "snes").mkdir()
            (roms / "n64").mkdir()
            touch(roms / "n64" / "game.n64")
            needed = cores.cores_for_systems(roms)
            self.assertIn("mupen64plus_next", needed)
            self.assertNotIn("snes9x", needed)   # folder exists but is empty


class TestEsDeSystemTable(unittest.TestCase):
    def test_parses_a_systems_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "es_systems.xml"
            p.write_text(
                '<?xml version="1.0"?><systemList>'
                '<system><name>psx</name><fullname>Sony PlayStation</fullname>'
                '<extension>.cue .CUE .chd</extension></system>'
                '<system><name>n64</name><fullname>Nintendo 64</fullname>'
                '<extension>.n64 .z64</extension></system>'
                '</systemList>', encoding="utf-8")
            table = esde.parse(p)
            self.assertEqual(set(table), {"psx", "n64"})
            self.assertEqual(table["psx"].fullname, "Sony PlayStation")
            self.assertIn(".cue", table["psx"].exts)

    def test_extension_index_maps_many_systems(self):
        table = {"a": esde.EsSystem("a", "A", {".iso"}),
                 "b": esde.EsSystem("b", "B", {".iso"})}
        self.assertEqual(set(esde.extension_index(table)[".iso"]), {"a", "b"})

    def test_malformed_file_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "es_systems.xml"
            p.write_text("<systemList><system><name>", encoding="utf-8")
            self.assertEqual(esde.parse(p), {})


class TestBios(unittest.TestCase):
    """BIOS requirements come from RetroArch's own core info files."""

    INFO = "\n".join([
        'display_name = "Sega Saturn"',
        'firmware_count = 2',
        'firmware0_desc = "sega_101.bin (Saturn JP BIOS)"',
        'firmware0_path = "sega_101.bin"',
        'firmware0_opt = "false"',
        'firmware1_desc = "mpr-17933.bin (Saturn US/EU BIOS)"',
        'firmware1_path = "mpr-17933.bin"',
        'firmware1_opt = "false"',
        'notes = "(!) sega_101.bin (md5): 85ec9ca47d8f6807718151cbcca8b964"',
    ])

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_parses_firmware_from_info_file(self):
        p = self.d / "mednafen_saturn_libretro.info"
        p.write_text(self.INFO, encoding="utf-8")
        reqs = bios.parse_info(p)
        self.assertEqual([b.name for b in reqs], ["sega_101.bin", "mpr-17933.bin"])
        self.assertTrue(all(b.required for b in reqs))

    def test_md5_is_taken_from_the_notes_field(self):
        p = self.d / "x_libretro.info"
        p.write_text(self.INFO, encoding="utf-8")
        reqs = bios.parse_info(p)
        self.assertEqual(reqs[0].md5, "85ec9ca47d8f6807718151cbcca8b964")
        self.assertIsNone(reqs[1].md5)

    def test_optional_firmware_is_not_required(self):
        p = self.d / "y_libretro.info"
        p.write_text("\n".join(['firmware_count = 1',
                                'firmware0_path = "gba_bios.bin"',
                                'firmware0_opt = "true"']), encoding="utf-8")
        self.assertFalse(bios.parse_info(p)[0].required)

    def test_info_file_without_firmware_yields_nothing(self):
        p = self.d / "z_libretro.info"
        p.write_text('display_name = "Thing"', encoding="utf-8")
        self.assertEqual(bios.parse_info(p), ())

    def test_missing_required_bios_is_blocking(self):
        b = bios.BiosFile("dc_boot.bin", None, True)
        st = [bios.BiosStatus("dreamcast", b, present=False)]
        self.assertEqual(len(bios.blocking(st)), 1)

    def test_missing_optional_bios_is_not_blocking(self):
        """A PS1 game runs without a BIOS; nagging about it would be noise."""
        b = bios.BiosFile("gba_bios.bin", None, False)
        st = [bios.BiosStatus("gba", b, present=False)]
        self.assertEqual(bios.blocking(st), [])

    def test_any_one_regional_bios_satisfies_the_system(self):
        jp = bios.BiosFile("sega_101.bin", None, True)
        us = bios.BiosFile("mpr-17933.bin", None, True)
        st = [bios.BiosStatus("saturn", jp, present=False),
              bios.BiosStatus("saturn", us, present=True)]
        self.assertEqual(bios.blocking(st), [])

    def test_wrong_checksum_is_always_blocking(self):
        b = bios.BiosFile("dc_boot.bin", "abc", True)
        st = [bios.BiosStatus("dreamcast", b, present=True, checksum_ok=False)]
        self.assertEqual(len(bios.blocking(st)), 1)
        self.assertEqual(st[0].state, "WRONG FILE")


class TestTidy(unittest.TestCase):
    """Repairing a library built before the one-entry-per-game rules."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.roms = Path(self.td.name) / "ROMs"
        (self.roms / "psx").mkdir(parents=True)
        (self.roms / "snes").mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def test_bin_beside_a_cue_is_flagged_as_data(self):
        (self.roms / "psx" / "Tekken 3.cue").write_text('FILE "Tekken 3.bin" BINARY')
        touch(self.roms / "psx" / "Tekken 3.bin")
        found = tidy.redundant_entries(self.roms)
        self.assertEqual([p.name for p, _ in found], ["Tekken 3.bin"])

    def test_cue_itself_is_never_flagged(self):
        (self.roms / "psx" / "Tekken 3.cue").write_text("x")
        touch(self.roms / "psx" / "Tekken 3.bin")
        self.assertNotIn("Tekken 3.cue",
                         [p.name for p, _ in tidy.redundant_entries(self.roms)])

    def test_disc_folder_behind_an_m3u_is_flagged(self):
        (self.roms / "psx" / "Chrono Cross.m3u").write_text("x")
        (self.roms / "psx" / "Chrono Cross").mkdir()
        found = tidy.unhidden_disc_folders(self.roms)
        self.assertEqual([p.name for p, _ in found], ["Chrono Cross"])

    def test_same_game_in_two_formats_is_a_duplicate(self):
        touch(self.roms / "snes" / "Super Metroid.sfc")
        touch(self.roms / "snes" / "Super Metroid.zip")
        dupes = tidy.duplicates(self.roms)
        self.assertEqual(len(dupes), 1)
        self.assertEqual(len(dupes[0].paths), 2)

    def test_one_copy_is_not_a_duplicate(self):
        touch(self.roms / "snes" / "Super Metroid.sfc")
        self.assertEqual(tidy.duplicates(self.roms), [])

    def test_stray_letter_folder_is_found(self):
        """Answering the drive question with "G" made a folder called G."""
        stray = self.roms.parent / "G"
        (stray / "ROMs" / "snes").mkdir(parents=True)
        (stray / "Incoming").mkdir(parents=True)
        found = tidy.stray_libraries(self.roms.parent)
        self.assertEqual([s.path.name for s in found], ["G"])
        self.assertTrue(found[0].safe_to_remove)

    def test_empty_stray_is_removed(self):
        stray = self.roms.parent / "G"
        (stray / "ROMs" / "snes").mkdir(parents=True)
        found = tidy.stray_libraries(self.roms.parent)
        tidy.remove_stray(found[0], dry_run=False)
        self.assertFalse(stray.exists())

    def test_stray_holding_games_is_never_removed(self):
        """By then it is someone's library, in the wrong place or not."""
        stray = self.roms.parent / "E"
        (stray / "ROMs" / "n64").mkdir(parents=True)
        touch(stray / "ROMs" / "n64" / "Real Game.n64")
        found = tidy.stray_libraries(self.roms.parent)
        self.assertFalse(found[0].safe_to_remove)
        tidy.remove_stray(found[0], dry_run=False)
        self.assertTrue((stray / "ROMs" / "n64" / "Real Game.n64").is_file())

    def test_dry_run_removes_nothing(self):
        stray = self.roms.parent / "G"
        (stray / "ROMs").mkdir(parents=True)
        found = tidy.stray_libraries(self.roms.parent)
        tidy.remove_stray(found[0], dry_run=True)
        self.assertTrue(stray.exists())

    def test_ordinary_folders_are_left_alone(self):
        """Only a single letter *and* a library tree inside counts."""
        (self.roms.parent / "G").mkdir()                    # letter, no library
        (self.roms.parent / "Games" / "ROMs").mkdir(parents=True)  # library, not a letter
        self.assertEqual(tidy.stray_libraries(self.roms.parent), [])

    def test_same_title_under_two_systems_is_reported(self):
        touch(self.roms / "snes" / "Turok.sfc")
        (self.roms / "n64").mkdir()
        touch(self.roms / "n64" / "Turok.n64")
        cross = tidy.cross_system_duplicates(self.roms)
        self.assertEqual(len(cross), 1)


class TestDrives(unittest.TestCase):
    """Where a library should live is measured, then offered - never assumed."""

    def _d(self, letter, free_gb, total_gb=1000, system=False, kind=drives.DRIVE_FIXED):
        return drives.Drive(letter, int(total_gb * drives.GB),
                            int(free_gb * drives.GB), kind, system)

    def test_lists_real_drives_biggest_first(self):
        found = drives.list_drives()
        self.assertTrue(found, "expected at least one drive")
        frees = [d.free for d in found]
        self.assertEqual(frees, sorted(frees, reverse=True))

    def test_suggestion_is_an_existing_drive(self):
        suggested = drives.suggest()
        self.assertTrue(suggested.endswith("Games"))
        letters = {d.letter for d in drives.list_drives()}
        self.assertIn(suggested[:2], letters)

    def test_low_space_drive_is_flagged(self):
        self.assertFalse(self._d("E:", 2).roomy)
        self.assertTrue(self._d("E:", 500).roomy)

    def test_describe_marks_the_system_drive(self):
        self.assertIn("system drive", self._d("C:", 500, system=True).describe())

    def test_free_space_is_reported_in_gb(self):
        self.assertAlmostEqual(self._d("D:", 250).free_gb, 250, places=3)


class TestArchiveVolumes(unittest.TestCase):
    """A 47-part set is one game, not 47. Only volume 1 is ever opened."""

    FIRST = ("X.part01.rar", "X.part1.rar", "X.part01", "X.7z.001",
             "X.zip.001", "X.001", "X.r00")
    LATER = ("X.part02.rar", "X.part47", "X.7z.002", "X.002", "X.r01")

    def test_first_volumes_recognised(self):
        for name in self.FIRST:
            self.assertTrue(archives.is_first_volume(name), name)
            self.assertFalse(archives.is_later_volume(name), name)

    def test_later_volumes_recognised(self):
        for name in self.LATER:
            self.assertTrue(archives.is_later_volume(name), name)
            self.assertFalse(archives.is_first_volume(name), name)

    def test_plain_archives_are_not_volumes(self):
        for name in ("Game.zip", "Game.7z", "Game.rar"):
            self.assertFalse(archives.is_first_volume(name), name)
            self.assertFalse(archives.is_later_volume(name), name)

    def test_volume_stem_is_shared_across_the_set(self):
        stems = {archives.volume_stem(n) for n in self.FIRST + self.LATER}
        self.assertEqual(stems, {"X"})

    def test_every_common_archive_extension_is_known(self):
        for ext in (".zip", ".7z", ".rar", ".tar", ".gz", ".xz", ".cab", ".lzh"):
            self.assertIn(ext, archives.ARCHIVE_EXTS)

    def test_zip_is_readable_without_seven_zip(self):
        self.assertTrue(archives.can_read("Game.zip"))

    def test_split_zip_needs_seven_zip_even_though_it_says_zip(self):
        """Game.zip.001 is not a zip file on its own."""
        self.assertEqual(archives.can_read("Game.zip.001"),
                         archives.sevenzip() is not None)


class TestClean(unittest.TestCase):
    """Deleting someone's game files: verify first, never on a dry run."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.drop = Path(self.td.name) / "Incoming"
        self.roms = Path(self.td.name) / "ROMs" / "n64"
        self.drop.mkdir(parents=True)
        self.roms.mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def _pair(self, name, body=b"identical bytes", other=None):
        (self.drop / name).write_bytes(body)
        (self.roms / name).write_bytes(other if other is not None else body)

    def test_identical_copy_is_safe_to_remove(self):
        self._pair("Zelda.n64")
        report = clean.survey([self.drop], [self.roms.parent])
        self.assertEqual(len(report.safe), 1)
        self.assertEqual(report.reclaimable, len(b"identical bytes"))

    def test_same_name_different_bytes_is_never_removed(self):
        self._pair("Zelda.n64", b"aaaa", other=b"bbbb")
        report = clean.survey([self.drop], [self.roms.parent])
        self.assertEqual(report.safe, [])
        self.assertEqual(len(report.mismatched), 1)

    def test_file_not_in_the_library_is_kept(self):
        (self.drop / "Unsorted.iso").write_bytes(b"x")
        report = clean.survey([self.drop], [self.roms.parent])
        self.assertEqual(report.safe, [])
        self.assertEqual(len(report.unmatched), 1)

    def test_dry_run_deletes_nothing(self):
        self._pair("Zelda.n64")
        report = clean.survey([self.drop], [self.roms.parent])
        clean.purge(report, dry_run=True, log=lambda *a: None)
        self.assertTrue((self.drop / "Zelda.n64").is_file())

    def test_purge_removes_only_the_drop_copy(self):
        self._pair("Zelda.n64")
        report = clean.survey([self.drop], [self.roms.parent])
        removed, freed = clean.purge(report, dry_run=False, log=lambda *a: None)
        self.assertEqual(removed, 1)
        self.assertFalse((self.drop / "Zelda.n64").exists())
        self.assertTrue((self.roms / "Zelda.n64").is_file())

    def test_quick_mode_matches_on_size_only(self):
        self._pair("Zelda.n64", b"aaaa", other=b"bbbb")     # same size
        self.assertEqual(len(clean.survey([self.drop], [self.roms.parent],
                                          quick=True).safe), 1)
        self.assertEqual(len(clean.survey([self.drop], [self.roms.parent],
                                          quick=False).safe), 0)

    def test_empty_folders_are_pruned_after_purge(self):
        nested = self.drop / "Some Game"
        nested.mkdir()
        (nested / "game.n64").write_bytes(b"z")
        (self.roms / "game.n64").write_bytes(b"z")
        report = clean.survey([self.drop], [self.roms.parent])
        clean.purge(report, dry_run=False, log=lambda *a: None)
        clean.prune_empty_dirs([self.drop], dry_run=False, log=lambda *a: None)
        self.assertFalse(nested.exists())
        self.assertTrue(self.drop.is_dir())


class TestCollections(ScanFixture):
    """A 3000-ROM set is 3000 games, and one stray .exe decides nothing."""

    def _zipped_rom(self, folder: Path, title: str, ext: str = ".md"):
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / f"{title}.zip", "w") as z:
            z.writestr(f"{title}{ext}", "x" * 64)

    def test_archive_of_many_games_is_a_collection(self):
        d = self.src / "MEGADRIVE_ROMS"
        d.mkdir(parents=True)
        inner = self.src / "build"
        for n in range(8):
            self._zipped_rom(inner, f"Game {n}")
        with zipfile.ZipFile(d / "MEGADRIVE_ROMS.zip", "w") as z:
            for p in inner.iterdir():
                z.write(p, f"MEGADRIVE_ROMS/{p.name}")
        for p in inner.iterdir():
            p.unlink()
        inner.rmdir()
        item = self.items()["MEGADRIVE ROMS"]
        self.assertTrue(item.collection)

    def test_single_game_archive_is_not_a_collection(self):
        self._zipped_rom(self.src, "Sonic")
        self.assertFalse(self.items()["Sonic"].collection)

    def test_collection_plan_stages_instead_of_filing(self):
        d = self.src / "MEGADRIVE_ROMS"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "MEGADRIVE_ROMS.zip", "w") as z:
            for n in range(8):
                z.writestr(f"Game {n}.md", "x" * 64)
        item = self.items()["MEGADRIVE ROMS"]
        pl = plan.build(item, self.cfg, staging=self.roms / ".staging")
        self.assertTrue(pl.get("stage"))
        self.assertTrue(any(a["type"] == "extract" for a in pl["actions"]))
        self.assertFalse(any(a["type"] == "copy" for a in pl["actions"]))

    def test_one_stray_exe_does_not_make_a_rom_set_a_windows_game(self):
        """3259 ROMs and one installer is not a Windows game."""
        d = self.src / "MEGADRIVE_ROMS"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "MEGADRIVE_ROMS.zip", "w") as z:
            for n in range(20):
                z.writestr(f"Game {n}.md", "x" * 64)
            z.writestr("readme_viewer.exe", "x")
        self.assertEqual(self.items()["MEGADRIVE ROMS"].system, "megadrive")

    def test_pc_game_archive_is_still_windows(self):
        self.src.mkdir(parents=True, exist_ok=True)
        p = self.src / "Space Blaster.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Game Files/game.exe", "x")
            z.writestr("README.txt", "unzip and run game.exe")
        self.assertEqual(self.items()["Space Blaster"].system, "windows")


class TestFolderBeatsTitle(ScanFixture):
    """A title containing a system word must not outrank the folder."""

    def _zipped(self, folder: Path, title: str):
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / f"{title}.zip", "w") as z:
            z.writestr(f"{title}.md", "x" * 64)

    def test_game_named_after_another_system_stays_put(self):
        d = self.src / "MEGADRIVE_ROMS_FULL_COLLECTION"
        for title in ("Phantasy Star 3 - Generations of Doom",
                      "Arrow Flash", "Censor C64 Picture Demo",
                      "Gauntlet Arcade Version"):
            self._zipped(d, title)
        systems = {i.system for i in scan.scan(d)}
        self.assertEqual(systems, {"megadrive"})

    def test_title_hint_still_works_without_a_folder_hint(self):
        touch(self.src / "Some PSX Game.pbp")
        self.assertEqual(self.items()["Some PSX Game"].system, "psx")


class TestPatching(unittest.TestCase):
    """Mods: apply IPS/BPS/UPS patches without ever touching the base ROM."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.base = bytes(range(256)) * 40
        (self.d / "game.sfc").write_bytes(self.base)

    def tearDown(self):
        self.td.cleanup()

    @staticmethod
    def _vlq(n: int) -> bytes:
        out = bytearray()
        while True:
            x = n & 0x7F
            n >>= 7
            if n == 0:
                out.append(0x80 | x)
                break
            out.append(x)
            n -= 1
        return bytes(out)

    def _bps_for(self, base: bytes) -> bytes:
        import struct
        import zlib
        body = (b"BPS1" + self._vlq(len(base)) + self._vlq(len(base))
                + self._vlq(0) + self._vlq(((len(base) - 1) << 2) | 0))
        crc = zlib.crc32(base) & 0xFFFFFFFF
        return body + struct.pack("<I", crc) + struct.pack("<I", crc) + struct.pack("<I", 0)

    def test_ips_applies_and_leaves_the_original_alone(self):
        ips = (b"PATCH" + (0x100).to_bytes(3, "big") + (4).to_bytes(2, "big")
               + b"MOD!" + b"EOF")
        (self.d / "hack.ips").write_bytes(ips)
        out = self.d / "patched.sfc"
        result = patch.apply_patch(self.d / "game.sfc", self.d / "hack.ips", out)
        self.assertEqual(result.format, "ips")
        self.assertEqual(out.read_bytes()[0x100:0x104], b"MOD!")
        self.assertEqual((self.d / "game.sfc").read_bytes(), self.base)

    def test_ips_rle_record(self):
        ips = (b"PATCH" + (0).to_bytes(3, "big") + (0).to_bytes(2, "big")
               + (5).to_bytes(2, "big") + bytes([0xAB]) + b"EOF")
        (self.d / "rle.ips").write_bytes(ips)
        out = self.d / "rle.sfc"
        patch.apply_patch(self.d / "game.sfc", self.d / "rle.ips", out)
        self.assertEqual(out.read_bytes()[:5], b"\xab" * 5)

    def test_bps_verifies_the_base_rom(self):
        (self.d / "hack.bps").write_bytes(self._bps_for(self.base))
        result = patch.apply_patch(self.d / "game.sfc", self.d / "hack.bps",
                                   self.d / "out.sfc")
        self.assertTrue(result.verified)

    def test_bps_refuses_the_wrong_base_rom(self):
        """Patching the wrong dump makes a game that breaks hours later."""
        (self.d / "hack.bps").write_bytes(self._bps_for(self.base))
        (self.d / "other.sfc").write_bytes(b"\x00" * len(self.base))
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(self.d / "other.sfc", self.d / "hack.bps",
                              self.d / "out.sfc")

    def test_unknown_format_is_rejected(self):
        (self.d / "bad.ips").write_bytes(b"not a patch at all")
        with self.assertRaises(patch.PatchError):
            patch.apply_patch(self.d / "game.sfc", self.d / "bad.ips",
                              self.d / "out.sfc")

    def test_dry_run_writes_nothing(self):
        (self.d / "hack.bps").write_bytes(self._bps_for(self.base))
        out = self.d / "out.sfc"
        patch.apply_patch(self.d / "game.sfc", self.d / "hack.bps", out, dry_run=True)
        self.assertFalse(out.exists())

    def test_pairs_a_lone_rom_with_every_patch(self):
        pairs = patch.find_pairs([self.d / "game.sfc", self.d / "a.ips",
                                  self.d / "b.bps"])
        self.assertEqual(len(pairs), 2)
        self.assertTrue(all(str(b).endswith("game.sfc") for b, _ in pairs))

    def test_no_patches_means_no_pairs(self):
        self.assertEqual(patch.find_pairs([self.d / "game.sfc"]), [])


class TestModPlan(ScanFixture):
    def test_patch_beside_a_rom_becomes_a_patch_action(self):
        d = self.src / "Zelda Randomizer"
        d.mkdir(parents=True)
        (d / "Zelda (USA).sfc").write_bytes(bytes(range(256)) * 4)
        (d / "Randomizer v3.ips").write_bytes(
            b"PATCH" + (0).to_bytes(3, "big") + (2).to_bytes(2, "big") + b"HI" + b"EOF")
        item = self.items()["Zelda Randomizer"]
        pl = plan.build(item, self.cfg)
        patches = [a for a in pl["actions"] if a["type"] == "patch"]
        self.assertEqual(len(patches), 1)
        self.assertIn("Randomizer v3", Path(patches[0]["dst"]).name)
        # the unmodified ROM is still copied, so both are playable
        self.assertTrue(any(a["type"] == "copy" and a["src"].endswith(".sfc")
                            for a in pl["actions"]))


class TestMediaExclusion(ScanFixture):
    """Box art must never become a game. ES-DE claims .png for pico8."""

    def test_png_beside_a_rom_is_not_a_game(self):
        d = self.src / "Sonic"
        touch(d / "Sonic (USA).md")
        touch(d / "cover.jpg")
        touch(d / "screenshot.png")
        item = self.items()["Sonic"]
        self.assertEqual(item.system, "megadrive")
        self.assertEqual(len(item.game_files), 1)
        self.assertEqual(item.media_count, 2)

    def test_loose_images_are_not_scanned_as_games(self):
        touch(self.src / "boxart.png")
        touch(self.src / "trailer.mp4")
        touch(self.src / "Zelda (USA).n64")
        self.assertEqual(list(self.items()), ["Zelda"])

    def test_folder_of_only_artwork_is_dropped(self):
        d = self.src / "Art Only"
        touch(d / "poster1.jpg")
        touch(d / "poster2.png")
        self.assertEqual(self.items(), {})

    def test_media_is_never_copied_into_the_library(self):
        d = self.src / "Sonic"
        touch(d / "Sonic (USA).md")
        touch(d / "cover.jpg")
        pl = plan.build(self.items()["Sonic"], self.cfg)
        copied = [Path(a["src"]).suffix.lower()
                  for a in pl["actions"] if a["type"] == "copy"]
        self.assertEqual(copied, [".md"])

    def test_unknown_extension_is_still_surfaced(self):
        """Media exclusion must not swallow genuinely unidentified files."""
        touch(self.src / "mystery.xyz")
        self.assertIn("mystery", self.items())


class TestDeduplication(unittest.TestCase):
    """A dump folder holds the same game four times over."""

    def test_verified_dump_beats_a_hack(self):
        self.assertLess(dedupe.rank("Sonic (USA) [!].md")[0],
                        dedupe.rank("Sonic (USA) [h1].md")[0])

    def test_quality_tag_beats_region(self):
        """"(USA) [h1]" is a hack that happens to be American."""
        self.assertGreater(dedupe.rank("Sonic (USA) [h1].md")[0],
                           dedupe.rank("Sonic (J).md")[0])

    def test_bad_dump_ranks_last(self):
        ranks = [dedupe.rank(n)[0] for n in
                 ("A [!].md", "A.md", "A [a1].md", "A [h1].md", "A [b1].md")]
        self.assertEqual(ranks, sorted(ranks))

    def test_us_preferred_over_japan_at_equal_quality(self):
        self.assertLess(dedupe.rank("Sonic (USA).md")[1],
                        dedupe.rank("Sonic (Japan).md")[1])

    def test_picks_one_copy_and_reports_the_rest(self):
        class FakeItem:
            def __init__(self, name):
                self.raw_name = name
                self.name = "Sonic the Hedgehog"
                self.system = "megadrive"
                self.total_size = 100
        items = [FakeItem(n) for n in (
            "Sonic the Hedgehog (USA) [h1].md",
            "Sonic the Hedgehog (USA) [!].md",
            "Sonic the Hedgehog (E).md")]
        kept, skipped = dedupe.pick_best(items)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].raw_name, "Sonic the Hedgehog (USA) [!].md")
        self.assertEqual(len(skipped), 2)

    def test_different_games_are_both_kept(self):
        class FakeItem:
            def __init__(self, name, title):
                self.raw_name = name
                self.name = title
                self.system = "megadrive"
                self.total_size = 100
        kept, skipped = dedupe.pick_best(
            [FakeItem("Sonic (USA).md", "Sonic"),
             FakeItem("Streets of Rage (USA).md", "Streets of Rage")])
        self.assertEqual(len(kept), 2)
        self.assertEqual(skipped, [])

    def test_unresolved_items_are_never_dropped_as_duplicates(self):
        class FakeItem:
            def __init__(self):
                self.raw_name = "Mystery.iso"
                self.name = "Mystery"
                self.system = None
                self.total_size = 1
        kept, skipped = dedupe.pick_best([FakeItem(), FakeItem()])
        self.assertEqual(len(kept), 2)
        self.assertEqual(skipped, [])


class TestProgress(unittest.TestCase):
    def test_fraction_uses_bytes_when_known(self):
        p = progress.Progress(total_items=10, total_bytes=1000, enabled=False)
        p.advance(items=1, nbytes=500)
        self.assertAlmostEqual(p.fraction, 0.5)

    def test_fraction_falls_back_to_item_count(self):
        p = progress.Progress(total_items=4, total_bytes=0, enabled=False)
        p.advance(items=1)
        self.assertAlmostEqual(p.fraction, 0.25)

    def test_eta_unknown_until_there_is_data(self):
        p = progress.Progress(total_items=10, total_bytes=1000, enabled=False)
        self.assertEqual(p.eta, -1)

    def test_human_helpers(self):
        self.assertEqual(progress.human_bytes(512), "512 B")
        self.assertEqual(progress.human_bytes(1536), "2 KB")
        self.assertEqual(progress.human_time(45), "45s")
        self.assertEqual(progress.human_time(125), "2m 05s")

    def test_totals_ignore_review_only_actions(self):
        plans = [{"actions": [
            {"type": "copy", "size": 100},
            {"type": "install", "size": 999, "needs_review": True},
            {"type": "mkdir"},
        ]}]
        self.assertEqual(progress.plan_totals(plans), (1, 100))


class TestUndo(unittest.TestCase):
    """A sort you cannot reverse is a sort you are afraid to run."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.d = Path(self.td.name)
        self.lib = self.d / "ROMs" / "snes"
        self.lib.mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def _run_with(self, *paths):
        run = history.Run(rom_dir=str(self.d / "ROMs"))
        for p in paths:
            run.add(p, "dir" if p.is_dir() else "file")
        return run

    def test_removes_what_the_sort_created(self):
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom data")
        run = self._run_with(game)
        res = history.undo(run, dry_run=False, log=lambda *a: None)
        self.assertEqual(res.removed_files, 1)
        self.assertFalse(game.exists())

    def test_dry_run_removes_nothing(self):
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom data")
        history.undo(self._run_with(game), dry_run=True, log=lambda *a: None)
        self.assertTrue(game.exists())

    def test_a_file_changed_since_the_sort_is_kept(self):
        """By then it is not esdeck's file to remove."""
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom data")
        run = self._run_with(game)
        game.write_bytes(b"something else entirely, different size")
        res = history.undo(run, dry_run=False, log=lambda *a: None)
        self.assertEqual(res.removed_files, 0)
        self.assertEqual(len(res.kept), 1)
        self.assertTrue(game.exists())

    def test_a_folder_that_still_holds_something_is_kept(self):
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom")
        keeper = self.lib / "NotMine.sfc"
        keeper.write_bytes(b"someone else put this here")
        run = self._run_with(game, self.lib)
        history.undo(run, dry_run=False, log=lambda *a: None)
        self.assertTrue(self.lib.is_dir())
        self.assertTrue(keeper.exists())

    def test_empty_folder_it_created_is_removed(self):
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom")
        run = self._run_with(game, self.lib)
        res = history.undo(run, dry_run=False, log=lambda *a: None)
        self.assertEqual(res.removed_dirs, 1)
        self.assertFalse(self.lib.exists())

    def test_missing_file_is_not_an_error(self):
        game = self.lib / "Gone.sfc"
        game.write_bytes(b"rom")
        run = self._run_with(game)
        game.unlink()
        res = history.undo(run, dry_run=False, log=lambda *a: None)
        self.assertEqual(res.removed_files, 0)
        self.assertEqual(res.kept, [])

    def test_run_round_trips_through_json(self):
        game = self.lib / "Zelda.sfc"
        game.write_bytes(b"rom data")
        run = self._run_with(game)
        run.sources = ["D:/Incoming"]
        back = history.Run.from_dict(json.loads(json.dumps(run.to_dict())))
        self.assertEqual(back.files, 1)
        self.assertEqual(back.sources, ["D:/Incoming"])
        self.assertEqual(back.created[0].path, str(game))


class TestLibraryCleanup(unittest.TestCase):
    """Repairing a library where artwork was filed as games."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.roms = Path(self.td.name) / "ROMs"
        for s in ("pico8", "tic80", "n64", "snes"):
            (self.roms / s).mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    @staticmethod
    def _png(path: Path, width: int = 640, height: int = 480):
        import struct
        import zlib

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                         + chunk(b"IEND", b""))

    def test_artwork_is_found_in_every_system_not_just_pico8(self):
        self._png(self.roms / "pico8" / "007 - The World Is Not Enough-image.png")
        self._png(self.roms / "tic80" / "Army Men-image.png")
        touch(self.roms / "n64" / "Mario 64 (USA).jpg")
        touch(self.roms / "snes" / "boxart.png")
        report = cleanup.find_junk(self.roms)
        self.assertEqual(len(report.junk), 4)
        self.assertEqual({j.system for j in report.junk},
                         {"pico8", "tic80", "n64", "snes"})

    def test_real_games_are_never_touched(self):
        touch(self.roms / "n64" / "Mario 64 (USA).n64")
        touch(self.roms / "snes" / "Zelda (USA).sfc")
        self.assertEqual(cleanup.find_junk(self.roms).junk, [])

    def test_a_genuine_pico8_cartridge_is_kept(self):
        """A real cart is a 160x205 PNG - deleting it would lose a game."""
        cart = self.roms / "pico8" / "Real Cart.p8.png"
        self._png(cart, 160, 205)
        report = cleanup.find_junk(self.roms)
        self.assertEqual(report.junk, [])
        self.assertEqual(len(report.kept), 1)

    def test_removal_frees_the_files(self):
        art = self.roms / "pico8" / "cover-image.png"
        self._png(art)
        report = cleanup.find_junk(self.roms)
        removed, _freed = cleanup.remove(report, dry_run=False, log=lambda *a: None)
        self.assertEqual(removed, 1)
        self.assertFalse(art.exists())

    def test_dry_run_removes_nothing(self):
        art = self.roms / "pico8" / "cover-image.png"
        self._png(art)
        cleanup.remove(cleanup.find_junk(self.roms), dry_run=True,
                       log=lambda *a: None)
        self.assertTrue(art.exists())

    def test_systems_left_empty_are_reported(self):
        self._png(self.roms / "tic80" / "art.png")
        touch(self.roms / "n64" / "Mario.n64")
        cleanup.remove(cleanup.find_junk(self.roms), dry_run=False,
                       log=lambda *a: None)
        empty = cleanup.systems_left_empty(self.roms)
        self.assertIn("tic80", empty)
        self.assertNotIn("n64", empty)


class TestControllerFix(unittest.TestCase):
    """The Xbox pad showing up as player 2."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.cfg = Path(self.td.name) / "retroarch.cfg"

    def tearDown(self):
        self.td.cleanup()

    def test_sets_player_one_to_the_first_pad(self):
        self.cfg.write_text('input_player1_joypad_index = "3"\n'
                            'input_joypad_driver = "dinput"\n', encoding="utf-8")
        controller.apply(self.cfg, controller.DESIRED, dry_run=False)
        got = controller.read_cfg(self.cfg)
        self.assertEqual(got["input_player1_joypad_index"], "0")
        self.assertEqual(got["input_joypad_driver"], "xinput")

    def test_leaves_other_settings_alone(self):
        self.cfg.write_text('video_fullscreen = "true"\n'
                            'input_player1_joypad_index = "2"\n', encoding="utf-8")
        controller.apply(self.cfg, controller.DESIRED, dry_run=False)
        self.assertEqual(controller.read_cfg(self.cfg)["video_fullscreen"], "true")

    def test_adds_a_missing_setting(self):
        self.cfg.write_text('video_fullscreen = "true"\n', encoding="utf-8")
        controller.apply(self.cfg, controller.DESIRED, dry_run=False)
        self.assertEqual(controller.read_cfg(self.cfg)["input_player1_joypad_index"], "0")

    def test_dry_run_changes_nothing(self):
        self.cfg.write_text('input_player1_joypad_index = "3"\n', encoding="utf-8")
        controller.apply(self.cfg, controller.DESIRED, dry_run=True)
        self.assertEqual(controller.read_cfg(self.cfg)["input_player1_joypad_index"], "3")

    def test_keyboard_is_never_disabled(self):
        """The keyboard is not a player and must keep working as a fallback."""
        self.assertNotIn("input_keyboard", " ".join(controller.DESIRED))
        for key in controller.DESIRED:
            self.assertNotIn("keyboard", key)

    def test_backup_is_written_once(self):
        self.cfg.write_text('input_player1_joypad_index = "3"\n', encoding="utf-8")
        original = self.cfg.read_text(encoding="utf-8")
        controller.apply(self.cfg, controller.DESIRED, dry_run=False)
        backup = self.cfg.with_suffix(".cfg.esdeck-backup")
        self.assertEqual(backup.read_text(encoding="utf-8"), original)


class TestEmulatorChoice(unittest.TestCase):
    """ES-DE's default is not always the one that works without a BIOS."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.es = Path(self.td.name) / "ES-DE"

    def tearDown(self):
        self.td.cleanup()

    def test_setting_creates_gamelist_with_the_label(self):
        emulators.set_emulator(self.es, "psx", "SwanStation")
        self.assertEqual(emulators.current(self.es, "psx"), "SwanStation")

    def test_setting_again_replaces_rather_than_duplicates(self):
        emulators.set_emulator(self.es, "psx", "SwanStation")
        emulators.set_emulator(self.es, "psx", "PCSX ReARMed")
        text = emulators.gamelist_path(self.es, "psx").read_text(encoding="utf-8")
        self.assertEqual(text.count("<alternativeEmulator>"), 1)
        self.assertEqual(emulators.current(self.es, "psx"), "PCSX ReARMed")

    def test_existing_games_are_preserved(self):
        path = emulators.gamelist_path(self.es, "psx")
        path.parent.mkdir(parents=True)
        path.write_text('<?xml version="1.0"?>\n<gameList>\n'
                        '<game><path>./x.m3u</path></game>\n</gameList>\n',
                        encoding="utf-8")
        emulators.set_emulator(self.es, "psx", "SwanStation")
        text = path.read_text(encoding="utf-8")
        self.assertIn("./x.m3u", text)
        self.assertIn("SwanStation", text)

    def test_dry_run_writes_nothing(self):
        emulators.set_emulator(self.es, "psx", "SwanStation", dry_run=True)
        self.assertFalse(emulators.gamelist_path(self.es, "psx").exists())

    def test_no_override_reads_as_none(self):
        self.assertIsNone(emulators.current(self.es, "psx"))

    def test_choice_travels_in_the_profile(self):
        """A working emulator pick should not be rediscovered on every PC."""
        cfg = config.Config(rom_dir="D:/ROMs", emulators={"psx": "SwanStation"})
        self.assertIn("emulators", config.profile_from(cfg))
        merged = config.apply_profile(config.Config(rom_dir="E:/ROMs"),
                                      config.profile_from(cfg))
        self.assertEqual(merged.emulators["psx"], "SwanStation")
        self.assertEqual(merged.rom_dir, "E:/ROMs")

    def test_psx_default_is_swanstation(self):
        self.assertEqual(emulators.DEFAULT_CHOICES["psx"], "SwanStation")
        self.assertEqual(config.Config().emulators.get("psx"), "SwanStation")


class TestConfigValidity(unittest.TestCase):
    """A config that cannot work must count as "not set up", so setup re-runs."""

    def test_relative_rom_dir_is_rejected(self):
        """The "G" answer produced rom_dir="G\\ROMs", which resolves nowhere."""
        cfg = config.Config(rom_dir="G" + chr(92) + "ROMs")
        self.assertFalse(config.is_usable(cfg))
        self.assertIn("relative", config.problems(cfg)[0])

    def test_absolute_rom_dir_is_fine(self):
        self.assertTrue(config.is_usable(config.Config(rom_dir="D:" + chr(92) + "ROMs")))

    def test_empty_rom_dir_is_rejected(self):
        self.assertFalse(config.is_usable(config.Config()))

    def test_relative_source_dir_is_reported(self):
        cfg = config.Config(rom_dir="D:" + chr(92) + "ROMs",
                            source_dirs=["G" + chr(92) + "Incoming"])
        self.assertFalse(config.is_usable(cfg))

    def test_corrupt_config_file_does_not_crash(self):
        """A damaged file should mean a fresh setup, not a traceback."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            p.write_text("{not json at all", encoding="utf-8")
            cfg = config.load(p)                 # falls back to autodetect
            self.assertIsInstance(cfg, config.Config)
            with self.assertRaises(config.BadConfig):
                config.load(p, strict=True)

    def test_config_that_is_not_an_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            p.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(config.BadConfig):
                config.load(p, strict=True)


if __name__ == "__main__":
    unittest.main()
