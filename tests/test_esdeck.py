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
from esdeck import config, esde, launcher, plan, readme_parse, scan, sniff  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
