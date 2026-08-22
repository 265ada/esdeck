"""esdeck command line.

    esdeck init            configure this machine (paths, autodetect)
    esdeck bootstrap       install ES-DE + emulators, create the ROM tree
    esdeck scan <dir>      show what esdeck thinks each dropped game is
    esdeck plan <dir>      write a reviewable plan.json
    esdeck apply <plan>    execute the safe half of a plan
    esdeck sync            do all of the above in one go (the usual command)
    esdeck cores           install RetroArch cores for your systems
    esdeck bios            check the BIOS files your systems need
    esdeck tidy            repair an existing library and find duplicates
    esdeck launchers       create .bat launchers for installed PC games
    esdeck link            point ES-DE at esdeck's ROM directory
    esdeck profile         export/import machine-independent settings
    esdeck doctor          check this machine's setup
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import apply as apply_mod
from . import bios as bios_mod
from . import bootstrap, config, cores as cores_mod, launcher, plan as plan_mod
from . import scan as scan_mod
from . import tidy as tidy_mod
from .systems import BY_KEY

DEFAULT_PLAN = "esdeck-plan.json"


def _p(*a, **kw):
    print(*a, **kw)


def _utf8_console() -> None:
    """Game titles are full of accents; the Windows console defaults to cp1252."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# --------------------------------------------------------------------- init
def cmd_init(args) -> int:
    cfg = config.load() if config.CONFIG_PATH.is_file() and not args.force else config.discover()
    if args.rom_dir:
        cfg.rom_dir = str(Path(args.rom_dir).expanduser())
    if args.es_config_dir:
        cfg.es_config_dir = str(Path(args.es_config_dir).expanduser())
    if args.install_dir:
        cfg.install_dir = str(Path(args.install_dir).expanduser())
    if args.source_dir:
        cfg.source_dirs = [str(Path(d).expanduser()) for d in args.source_dir]
    if not cfg.install_dir or (args.rom_dir and not args.install_dir):
        cfg.install_dir = str(Path(cfg.rom_dir) / "windows")
    path = config.save(cfg)
    _p(f"Wrote {path}")
    for k, v in cfg.to_dict().items():
        _p(f"  {k:16} {v}")
    return 0


# ---------------------------------------------------------------- bootstrap
def cmd_bootstrap(args) -> int:
    cfg = config.load()
    pkgs = args.packages or list(bootstrap.DEFAULT_PACKAGES)
    if args.all_emulators:
        pkgs = list(bootstrap.PACKAGES)
    _p(f"{'DRY RUN - ' if not args.yes else ''}bootstrapping with ROM dir {cfg.rom_dir}")
    bootstrap.run(cfg, packages=pkgs, dry_run=not args.yes, repair=args.repair, log=_p)
    if not args.yes:
        _p("\nRe-run with --yes to actually install.")
    return 0


# --------------------------------------------------------------------- scan
def _describe(item) -> None:
    conf = {"high": "OK  ", "medium": "?   ", "low": "??  "}[item.confidence]
    sysname = item.system or ("UNRECOGNIZED" if item.unrecognized else "UNKNOWN")
    _p(f"{conf} {item.name}  ->  {sysname}  ({len(item.files)} files, "
       f"{item.total_size / 1_048_576:.0f} MB)")
    if item.candidates:
        _p(f"       also plausible: {', '.join(item.candidates)}")
    for rel in item.opaque_archives:
        _p(f"       {rel}: cannot inspect without 7-Zip; extract it yourself first")
    if item.unrecognized:
        _p("       no recognizable game files - listed so it is not silently skipped")
    if item.hints:
        h = item.hints
        bits = []
        if h.flags:
            bits.append("flags: " + ",".join(h.flags))
        if h.emulators:
            bits.append("emulators: " + ",".join(h.emulators))
        if h.commands:
            bits.append(f"{len(h.commands)} suggested command(s)")
        _p(f"       readme {h.source}: " + ("; ".join(bits) if bits else "no actionable hints"))
    for w in bios_mod.warn_lines(item.system) if item.system else []:
        _p(f"       BIOS: {w}")


def _sources(args, cfg) -> list[Path]:
    """The folders to scan: an explicit path, else the configured drop folders."""
    if args.source:
        return [Path(args.source)]
    return [Path(d) for d in cfg.source_dirs]


def cmd_scan(args) -> int:
    cfg = config.load()
    sources = _sources(args, cfg)
    if not sources:
        _p("No drop folder given or configured.")
        _p("  esdeck scan <dir>            scan a folder once")
        _p("  esdeck init --source-dir X   remember X as your drop folder")
        return 2
    items = []
    for src in sources:
        if not src.exists():
            _p(f"skip {src}: does not exist")
            continue
        items.extend(scan_mod.scan(src))
    if not items:
        _p("Nothing found.")
        return 1
    for item in items:
        _describe(item)
    if args.json:
        Path(args.json).write_text(
            json.dumps([i.to_dict() for i in items], indent=2), encoding="utf-8")
        _p(f"\nWrote {args.json}")
    return 0


# --------------------------------------------------------------------- plan
def cmd_plan(args) -> int:
    cfg = config.load()
    if not cfg.rom_dir:
        _p("No ROM directory configured. Run: esdeck init --rom-dir <path>")
        return 2
    sources = _sources(args, cfg)
    if not sources:
        _p("No drop folder given or configured. Pass one, or set a default with:")
        _p(r"  esdeck init --source-dir D:\Games\Incoming")
        return 2
    items = []
    for src in sources:
        if not src.exists():
            _p(f"skip {src}: does not exist")
            continue
        items.extend(scan_mod.scan(src))
    if args.system:
        if args.system not in BY_KEY:
            _p(f"Unknown system {args.system!r}. Known: {', '.join(sorted(BY_KEY))}")
            return 2
        for i in items:
            i.system, i.candidates, i.confidence = args.system, [], "high"
    bundle = plan_mod.build_all(items, cfg)
    for pl in bundle["plans"]:
        _p(f"\n{pl['name']}  [{pl['system'] or 'UNKNOWN'}, {pl['confidence']}]")
        _p(f"  {plan_mod.summarize(pl)}")
        for w in pl["warnings"]:
            _p(f"  ! {w}")
    out = Path(args.out or DEFAULT_PLAN)
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    _p(f"\nWrote {out}. Review it, then: esdeck apply {out} --yes")
    return 0


# -------------------------------------------------------------------- apply
def cmd_apply(args) -> int:
    cfg = config.load()
    bundle = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    plans = bundle["plans"] if "plans" in bundle else [bundle]
    roots = [cfg.rom_dir, cfg.install_dir] if not args.unsafe_any_path else []
    total_manual: list[str] = []
    failed = 0

    for pl in plans:
        if not pl.get("system") and not args.allow_unknown:
            _p(f"SKIP {pl['name']}: system unknown (use --allow-unknown to place under UNKNOWN/)")
            continue
        _p(f"\n{pl['name']} -> {pl['system']}")
        res = apply_mod.apply_plan(pl, dry_run=not args.yes, roots=roots,
                                   overwrite=args.overwrite, log=_p)
        _p(f"  {res}")
        failed += len(res.errors)
        total_manual.extend(f"[{pl['name']}] {s}" for s in apply_mod.manual_steps(pl))

    if total_manual:
        _p("\nManual steps left for you (nothing below was executed):")
        for s in total_manual:
            _p(f"  - {s}")
    if not args.yes:
        _p("\nDRY RUN. Re-run with --yes to write files.")
    return 1 if failed else 0


# --------------------------------------------------------------------- sync
def cmd_sync(args) -> int:
    """The one command: sort what was dropped, then make it launchable.

    Everything it does is a dry run until --yes, and the review-only actions
    stay review-only - sync never runs an installer or a README command.
    """
    cfg = config.load()
    if not cfg.rom_dir:
        _p("Not set up yet. Run: esdeck init --rom-dir D:\\ROMs")
        return 2

    sources = _sources(args, cfg)
    if not sources:
        _p("No drop folder configured. Run:")
        _p(r"  esdeck init --source-dir D:\Games\Incoming")
        return 2

    header = "esdeck sync" if args.yes else "esdeck sync (DRY RUN)"
    _p(f"{header}  {', '.join(str(s) for s in sources)} -> {cfg.rom_dir}\n")

    # 1. What is in the drop folder?
    _p("[1/4] Reading the drop folder")
    items = []
    for src in sources:
        if not src.exists():
            _p(f"  skip {src}: does not exist")
            continue
        items.extend(scan_mod.scan(src))
    if not items:
        _p("  nothing to do - the drop folder is empty")
        return 0
    if args.system:
        if args.system not in BY_KEY:
            _p(f"  unknown system {args.system!r}")
            return 2
        for i in items:
            i.system, i.candidates, i.confidence = args.system, [], "high"
    for item in items:
        _describe(item)

    # 2. File them into the library.
    _p("\n[2/4] Filing games into the library")
    bundle = plan_mod.build_all(items, cfg)
    roots = [cfg.rom_dir, cfg.install_dir]
    manual: list[str] = []
    unresolved, errors = [], 0
    for pl in bundle["plans"]:
        if not pl.get("system"):
            unresolved.append(pl["name"])
            continue
        res = apply_mod.apply_plan(pl, dry_run=not args.yes, roots=roots,
                                   overwrite=args.overwrite, log=lambda *a: None)
        errors += len(res.errors)
        _p(f"  {pl['name']} -> {pl['system']}: {res}")
        for e in res.errors:
            _p(f"    ERROR {e}")
        manual.extend(f"[{pl['name']}] {s}" for s in apply_mod.manual_steps(pl))

    # 3. Cores, so the new systems can actually launch.
    if args.no_cores:
        _p("\n[3/4] Cores: skipped (--no-cores)")
    else:
        _p("\n[3/4] RetroArch cores")
        cores_mod.run(Path(cfg.rom_dir), dry_run=not args.yes, log=lambda s: _p(f"  {s}"))

    # 4. Launchers for any PC game that landed as a folder.
    _p("\n[4/4] PC game launchers")
    made = 0
    for g in launcher.scan_install_dir(Path(cfg.install_dir), Path(cfg.rom_dir)):
        if g["has_launcher"]:
            continue
        if not g["candidates"]:
            _p(f"  SKIP {g['name']}: no game .exe yet (installer not run?)")
            continue
        _p("  " + launcher.write_launcher(g["dest"], g["candidates"][0],
                                          dry_run=not args.yes))
        made += 1
    if not made:
        _p("  nothing to do")

    # What is left for a human.
    if unresolved:
        _p(f"\nNeeds a decision - system could not be determined: {', '.join(unresolved)}")
        _p("  re-run with --system <key>, e.g. esdeck sync --system psx")
    if manual:
        _p("\nManual steps (nothing below was executed):")
        for s in manual:
            _p(f"  - {s}")

    if not args.yes:
        _p("\nDRY RUN - nothing was changed. Re-run with --yes to do it.")
    else:
        _p("\nDone. Restart ES-DE (or press F5 in it) to see the new games.")
    return 1 if errors else 0


# --------------------------------------------------------------------- tidy
def cmd_tidy(args) -> int:
    """Repair a library: one entry per game, and report duplicate copies."""
    cfg = config.load()
    rom_dir = Path(cfg.rom_dir)
    if not rom_dir.is_dir():
        _p(f"No ROM directory at {rom_dir}")
        return 2

    fixes = tidy_mod.redundant_entries(rom_dir) + tidy_mod.unhidden_disc_folders(rom_dir)
    _p(f"{'Hiding' if args.yes else 'Would hide'} {len(fixes)} item(s) so each game "
       f"shows once in ES-DE")
    for path, why in fixes:
        _p(f"  {path.relative_to(rom_dir)}  ({why})")
        if args.yes:
            apply_mod.set_hidden(path)

    dupes = tidy_mod.duplicates(rom_dir)
    if dupes:
        _p("")
        _p(f"{len(dupes)} duplicate game(s) - same title, more than one copy:")
        for d in dupes:
            _p(f"  {d.describe()}")
        _p("  Not touched: which copy to keep is your call.")

    cross = tidy_mod.cross_system_duplicates(rom_dir)
    if cross:
        _p("")
        _p(f"{len(cross)} title(s) filed under more than one system:")
        for d in cross:
            _p(f"  {d.describe()}")

    if not fixes and not dupes and not cross:
        _p("Nothing to do - the library is already tidy.")
    elif fixes and not args.yes:
        _p("")
        _p("DRY RUN. Re-run with --yes to hide the data files.")
    return 0


# --------------------------------------------------------------------- bios
def cmd_bios(args) -> int:
    """Report which BIOS files your systems need and whether you have them."""
    cfg = config.load()
    sysdir = bios_mod.system_dir()
    if sysdir is None:
        _p("RetroArch not found - install it first (esdeck bootstrap --yes)")
        return 2

    keys = [args.system] if args.system else sorted(
        d.name for d in Path(cfg.rom_dir).iterdir()
        if d.is_dir() and any(d.iterdir()) and bios_mod.requirements_for(d.name))
    if not keys:
        _p("No systems in your library need a BIOS file.")
        return 0

    _p(f"BIOS folder: {sysdir}\n")
    problems = 0
    for key in keys:
        statuses = bios_mod.check_system(key)
        if not statuses:
            continue
        blockers = bios_mod.blocking(statuses)
        problems += len(blockers)
        _p(f"{key}  {'PROBLEM' if blockers else 'ok'}")
        for st in statuses:
            if args.all or st.state != "missing (optional)":
                note = f"  ({st.bios.note})" if st.bios.note else ""
                _p(f"    {st.state:20} {st.bios.name}{note}")
        for w in bios_mod.warn_lines(key):
            _p(f"    -> {w}")

    if problems:
        _p("")
        _p("esdeck does not download BIOS files - they are copyrighted console")
        _p("firmware, which is why RetroArch's own updater does not fetch them either.")
        _p(f"Put the files named above into {sysdir} and re-run this to verify them.")
    return 1 if problems else 0


# -------------------------------------------------------------------- cores
def cmd_cores(args) -> int:
    """Install the RetroArch cores needed by the systems that have games."""
    cfg = config.load()
    only = args.core
    if args.all:
        only = cores_mod.all_cores()
    elif args.common:
        only = list(cores_mod.COMMON_CORES)
    cores_mod.run(Path(cfg.rom_dir), only=only, dry_run=not args.yes, log=_p)
    if not args.yes:
        _p("\nDRY RUN. Re-run with --yes to download from the libretro buildbot.")
    return 0


# ---------------------------------------------------------------- launchers
def cmd_launchers(args) -> int:
    """Give installed PC games a .bat so ES-DE's windows system can see them."""
    cfg = config.load()
    games = launcher.scan_install_dir(Path(cfg.install_dir), Path(cfg.rom_dir))
    if not games:
        _p(f"No installed PC game folders under {cfg.install_dir}")
        return 0

    made = 0
    for g in games:
        if g["has_launcher"] and not args.overwrite:
            _p(f"  ok     {g['name']}: launcher already present")
            continue
        if not g["candidates"]:
            _p(f"  SKIP   {g['name']}: no game .exe found in {g['folder']}")
            continue
        if len(g["candidates"]) > 1 and not args.first:
            _p(f"  ?      {g['name']}: {len(g['candidates'])} candidates, pick one with --exe")
            for c in g["candidates"][:5]:
                _p(f"           {c}")
            continue
        exe = Path(args.exe) if args.exe else g["candidates"][0]
        _p(f"  make   {launcher.write_launcher(g['dest'], exe, dry_run=not args.yes, overwrite=args.overwrite)}")
        made += 1

    if made and not args.yes:
        _p("\nDRY RUN. Re-run with --yes to write the launchers.")
    return 0


# --------------------------------------------------------------------- link
def cmd_link(args) -> int:
    """Point ES-DE's own settings at the library esdeck manages."""
    cfg = config.load()
    if bootstrap.es_de_running():
        _p("ES-DE is running - it rewrites es_settings.xml on exit, which would")
        _p("discard these changes. Quit ES-DE first, then re-run.")
        return 2
    values = {"ROMDirectory": cfg.rom_dir}
    if cfg.media_dir:
        values["MediaDirectory"] = cfg.media_dir
    # esdeck hides the data half of multi-file games (.bin next to .cue, the
    # disc folder behind an .m3u). ES-DE only respects that with this off.
    values["ShowHiddenFiles"] = "false"
    try:
        changes = config.write_es_settings(Path(cfg.es_config_dir), values,
                                           dry_run=not args.yes, create=args.create)
    except FileNotFoundError as exc:
        _p(f"error: {exc}")
        return 2
    for c in changes:
        _p(f"  {c}")
    if not args.yes:
        _p("\nDRY RUN. Re-run with --yes to write es_settings.xml.")
    else:
        _p(f"\nES-DE will now read games from {cfg.rom_dir}. Restart ES-DE to pick it up.")
    return 0


# ------------------------------------------------------------------ profile
def cmd_profile(args) -> int:
    cfg = config.load()
    if args.action == "export":
        data = config.profile_from(cfg)
        out = Path(args.file or "esdeck-profile.json")
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _p(f"Wrote {out} ({len(data)} settings, no machine-specific paths).")
    else:
        if not args.file:
            _p("Usage: esdeck profile import --file esdeck-profile.json")
            return 2
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        cfg = config.apply_profile(cfg, data)
        config.save(cfg)
        _p(f"Applied profile from {args.file}; local paths untouched.")
    return 0


# ------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    cfg = config.load()
    problems = 0

    def check(ok: bool, label: str, fix: str = "") -> None:
        nonlocal problems
        _p(f"  {'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            problems += 1
            if fix:
                _p(f"       fix: {fix}")

    _p(f"Config: {config.CONFIG_PATH}{'' if config.CONFIG_PATH.is_file() else ' (not written yet)'}")
    check(bool(cfg.rom_dir) and Path(cfg.rom_dir).is_dir(),
          f"ROM directory {cfg.rom_dir}", "esdeck init --rom-dir <path>")
    es_binary = bootstrap.find_es_de()
    check(es_binary is not None,
          f"ES-DE installed{f' ({es_binary})' if es_binary else ''}",
          "esdeck bootstrap --packages es-de --yes")
    # ES-DE only creates its config dir on first launch, so an installed-but-never-run
    # ES-DE is a different problem from a missing one.
    check(Path(cfg.es_config_dir).is_dir(),
          f"ES-DE config dir {cfg.es_config_dir}",
          "launch ES-DE once - it creates this on first run"
          if es_binary else "install ES-DE first")
    settings = config.read_es_settings(Path(cfg.es_config_dir))
    check(bool(settings), "es_settings.xml readable", "launch ES-DE once so it writes its settings")
    if settings.get("ROMDirectory") and cfg.rom_dir:
        same = Path(settings["ROMDirectory"]).expanduser() == Path(cfg.rom_dir)
        check(same or settings["ROMDirectory"] == "%ROMPATH%",
              f"ES-DE ROM dir matches esdeck ({settings['ROMDirectory']})",
              f"point ES-DE at {cfg.rom_dir} or re-run esdeck init")
    if settings.get("ShowHiddenFiles") == "true":
        check(False, "ES-DE hides esdeck's data files (ShowHiddenFiles)",
              "esdeck link --yes  (otherwise every disc of a game is listed twice)")
    sysdir = bios_mod.system_dir()
    if sysdir and Path(cfg.rom_dir).is_dir():
        missing = []
        for d in sorted(Path(cfg.rom_dir).iterdir()):
            if d.is_dir() and any(d.iterdir()):
                missing.extend(bios_mod.blocking(bios_mod.check_system(d.name)))
        check(not missing,
              f"BIOS files present for your systems ({len(missing)} missing)"
              if missing else "BIOS files present for your systems",
              "esdeck bios  (lists the exact files; esdeck cannot download them)")
    check(bootstrap.have_winget(), "winget available", "install App Installer from the MS Store")
    _p(f"\n{'No problems found.' if not problems else f'{problems} problem(s) found.'}")
    return 1 if problems else 0


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="esdeck", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="configure this machine")
    p.add_argument("--rom-dir")
    p.add_argument("--es-config-dir")
    p.add_argument("--install-dir")
    p.add_argument("--source-dir", action="append",
                   help="drop folder to scan when no path is given (repeatable)")
    p.add_argument("--force", action="store_true", help="re-autodetect, discard existing config")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("bootstrap", help="install ES-DE/emulators and create the ROM tree")
    p.add_argument("--packages", nargs="*", help=f"subset of {', '.join(bootstrap.PACKAGES)}")
    p.add_argument("--all-emulators", action="store_true")
    p.add_argument("--repair", action="store_true",
                   help="reinstall over an existing install (backs up saves/config first)")
    p.add_argument("--yes", action="store_true", help="actually install (default is a dry run)")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("scan", help="identify dropped games")
    p.add_argument("source", nargs="?", help="defaults to the configured drop folder(s)")
    p.add_argument("--json", help="also write the raw scan to this file")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("plan", help="build a reviewable install plan")
    p.add_argument("source", nargs="?", help="defaults to the configured drop folder(s)")
    p.add_argument("--out")
    p.add_argument("--system", help="force a system for every item")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", help="execute the safe half of a plan")
    p.add_argument("plan", nargs="?", default=DEFAULT_PLAN)
    p.add_argument("--yes", action="store_true", help="write files (default is a dry run)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--allow-unknown", action="store_true",
                   help="place unidentified games under <ROMs>/UNKNOWN/")
    p.add_argument("--unsafe-any-path", action="store_true",
                   help="disable the write-outside-ROM-dir guard")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("tidy", help="repair an existing library and find duplicates")
    p.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    p.set_defaults(func=cmd_tidy)

    p = sub.add_parser("bios", help="check BIOS files your systems need")
    p.add_argument("--system", help="check one system only")
    p.add_argument("--all", action="store_true", help="include optional files")
    p.set_defaults(func=cmd_bios)

    p = sub.add_parser("cores", help="install RetroArch cores for your systems")
    p.add_argument("--core", action="append", help="specific core name (repeatable)")
    p.add_argument("--common", action="store_true",
                   help="install a starter set covering the common systems")
    p.add_argument("--all", action="store_true", help="install every core esdeck knows")
    p.add_argument("--yes", action="store_true", help="download (default is a dry run)")
    p.set_defaults(func=cmd_cores)

    p = sub.add_parser("launchers", help="create .bat launchers for installed PC games")
    p.add_argument("--yes", action="store_true", help="write (default is a dry run)")
    p.add_argument("--exe", help="use this executable instead of the detected one")
    p.add_argument("--first", action="store_true", help="accept the best guess when ambiguous")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_launchers)

    p = sub.add_parser("link", help="point ES-DE's settings at esdeck's ROM directory")
    p.add_argument("--yes", action="store_true", help="write (default is a dry run)")
    p.add_argument("--create", action="store_true",
                   help="write a minimal es_settings.xml if ES-DE has never been launched")
    p.set_defaults(func=cmd_link)

    p = sub.add_parser("profile", help="share settings between computers")
    p.add_argument("action", choices=("export", "import"))
    p.add_argument("--file")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("sync", help="do everything: sort the drop folder, then finish the setup")
    p.add_argument("source", nargs="?", help="defaults to the configured drop folder(s)")
    p.add_argument("--yes", action="store_true", help="actually do it (default is a dry run)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--system", help="force a system for every item")
    p.add_argument("--no-cores", action="store_true", help="skip the RetroArch core step")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("doctor", help="check this machine's setup")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv=None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as exc:
        _p(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
