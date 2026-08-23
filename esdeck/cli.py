"""esdeck command line.

    esdeck init            configure this machine (paths, autodetect)
    esdeck bootstrap       install ES-DE + emulators, create the ROM tree
    esdeck scan <dir>      show what esdeck thinks each dropped game is
    esdeck plan <dir>      write a reviewable plan.json
    esdeck apply <plan>    execute the safe half of a plan
    esdeck sync            do all of the above in one go (the usual command)
    esdeck cores           install RetroArch cores for your systems
    esdeck bios            check the BIOS files your systems need
    esdeck emulators       show or set which emulator ES-DE uses
    esdeck undo            reverse a previous sort
    esdeck history         list previous sorts
    esdeck update          check GitHub and install a newer esdeck
    esdeck cleanup         remove artwork an older version filed as games
    esdeck controller      make the game controller player 1
    esdeck tidy            repair an existing library and find duplicates
    esdeck clean           free space: remove drop-folder copies already filed
    esdeck launchers       create .bat launchers for installed PC games
    esdeck link            point ES-DE at esdeck's ROM directory
    esdeck profile         export/import machine-independent settings
    esdeck doctor          check this machine's setup
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import apply as apply_mod
from . import bios as bios_mod
from . import bootstrap, clean as clean_mod, cleanup as cleanup_mod, config
from . import controller as controller_mod, cores as cores_mod
from . import dedupe as dedupe_mod
from . import drives as drives_mod
from . import emulators as emu_mod
from . import history as history_mod
from . import icon as icon_mod
from . import launcher, plan as plan_mod
from . import progress as progress_mod
from . import scan as scan_mod
from . import tidy as tidy_mod
from . import update as update_mod
from . import __version__
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


# -------------------------------------------------------------- checksetup
def cmd_checksetup(args) -> int:
    """Exit 0 only if this machine is configured usably. For esdeck.bat.

    Deliberately stricter than "config.json exists": a config pointing at a
    relative ROM directory made setup skip itself forever while sorting
    nothing.
    """
    if not config.CONFIG_PATH.is_file():
        _p("not configured yet")
        return 1
    try:
        cfg = config.load(strict=True)
    except config.BadConfig as exc:
        _p(f"broken config: {exc}")
        return 1
    issues = config.problems(cfg)
    if issues:
        for i in issues:
            _p(f"broken config: {i}")
        return 1
    if not Path(cfg.rom_dir).is_dir():
        _p(f"ROM directory does not exist: {cfg.rom_dir}")
        return 1
    _p("configured")
    return 0


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

    # A config carried over from another PC can name that PC's user folder,
    # e.g. another user's ES-DE directory. If the configured path is not there,
    # fall back to this machine's own location rather than keeping a dead one.
    if not args.es_config_dir and not Path(cfg.es_config_dir or "x").is_dir():
        detected = config.default_es_config_dir()
        if str(detected) != cfg.es_config_dir:
            cfg.es_config_dir = str(detected)
            if not cfg.media_dir or not Path(cfg.media_dir).is_absolute():
                cfg.media_dir = str(detected / "downloaded_media")
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
    extra = f", {item.media_count} image(s) ignored" if item.media_count else ""
    _p(f"{conf} {item.name}  ->  {sysname}  ({len(item.game_files)} file(s), "
       f"{item.total_size / 1_048_576:.0f} MB{extra})")
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
    _es = Path(config.load().es_config_dir)
    for w in (bios_mod.warn_lines(item.system, es_config_dir=_es)
              if item.system else []):
        _p(f"       BIOS: {w}")


def _sources(args, cfg) -> list[Path]:
    """Folders to scan: any given on the command line, else the configured ones.

    Several can be given at once - a whole list of drop folders is scanned in
    one pass, and duplicates are collapsed so overlapping paths do not sort the
    same game twice.
    """
    given = getattr(args, "source", None)
    if isinstance(given, str):
        given = [given]
    paths = [Path(p) for p in (given or cfg.source_dirs)]
    seen, out = set(), []
    for p in paths:
        key = str(p.resolve()).lower() if p.exists() else str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


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
    #
    # This is the slow half on a big collection: every archive is opened to
    # list what is inside and every disc image is read for its signature. It
    # therefore reports as it goes, or a long scan looks exactly like a hang.
    _p("[1/4] Reading the drop folder")
    items = []
    seen = [0]
    scan_bar = progress_mod.Progress(enabled=True)

    def scanning(name):
        seen[0] += 1
        scan_bar.advance(items=1, label=f"{seen[0]} examined: {name}")

    for src in sources:
        if not src.exists():
            _p(f"  skip {src}: does not exist")
            continue
        items.extend(scan_mod.scan(src, on_progress=scanning))
    scan_bar.finish(f"  examined {seen[0]} item(s) in "
                    f"{progress_mod.human_time(scan_bar.elapsed)}"
                    if seen[0] else "")
    if not items:
        _p("  nothing to do - the drop folder is empty")
        return 0
    if args.system:
        if args.system not in BY_KEY:
            _p(f"  unknown system {args.system!r}")
            return 2
        for i in items:
            i.system, i.candidates, i.confidence = args.system, [], "high"
    # Messy collections hold the same game several times over. Keep the best
    # copy of each and say which ones were passed over.
    duplicates = []
    if not args.keep_duplicates:
        items, duplicates = dedupe_mod.pick_best(items)

    for item in items:
        _describe(item)
    if duplicates:
        _p("")
        _p(f"  {len(duplicates)} duplicate(s) skipped - one copy kept per game:")
        for d in duplicates[:10]:
            _p(f"    {d.describe()}")
        if len(duplicates) > 10:
            _p(f"    ... and {len(duplicates) - 10} more "
               f"(use --keep-duplicates to file them all)")

    # 2. File them into the library.
    _p("\n[2/4] Filing games into the library")
    staging = Path(cfg.rom_dir) / ".esdeck-staging"
    bundle = plan_mod.build_all(items, cfg, staging=staging)
    roots = [cfg.rom_dir, cfg.install_dir]
    manual: list[str] = []
    unresolved, errors = [], 0
    staged = False

    # Progress and an estimate: a few thousand games is tens of GB and minutes
    # of copying, which without feedback looks exactly like a hung program.
    journal = history_mod.Run(label="sync", rom_dir=cfg.rom_dir,
                              sources=[str(x) for x in sources])
    n_items, n_bytes = progress_mod.plan_totals(bundle["plans"])
    bar = progress_mod.Progress(total_items=n_items, total_bytes=n_bytes,
                                enabled=args.yes and n_items > 1)

    def tick(kind, nbytes, label):
        bar.advance(items=1, nbytes=nbytes, label=label)

    def run_plan(pl, indent="  "):
        nonlocal errors
        res = apply_mod.apply_plan(pl, dry_run=not args.yes, roots=roots,
                                   overwrite=args.overwrite, log=lambda *a: None,
                                   on_progress=tick)
        for made, kind in res.created:
            journal.add(made, kind)
        errors += len(res.errors)
        if not bar.enabled:
            _p(f"{indent}{pl['name']} -> {pl['system']}: {res}")
        for e in res.errors:
            bar.finish()
            _p(f"{indent}  ERROR {e}")
        manual.extend(f"[{pl['name']}] {s}" for s in apply_mod.manual_steps(pl))

    for pl in bundle["plans"]:
        if pl.get("stage"):
            _p(f"  {pl['name']}: collection - unpacking to sort each game separately")
            if args.yes:
                res = apply_mod.apply_plan(pl, dry_run=False, roots=roots,
                                           overwrite=args.overwrite,
                                           log=lambda *a: None, on_progress=tick)
                for made, kind in res.created:
                    journal.add(made, kind)
                errors += len(res.errors)
                for e in res.errors:
                    _p(f"    ERROR {e}")
                staged = True
            continue
        if not pl.get("system"):
            unresolved.append(pl["name"])
            continue
        run_plan(pl)

    # Second pass: whatever came out of a collection is scanned and sorted as
    # individual games, so a 3000-ROM set becomes 3000 entries, not one.
    if staged and staging.is_dir():
        inner = scan_mod.scan(staging)
        _p(f"\n  unpacked {len(inner)} item(s) - sorting each one")
        inner_bundle = plan_mod.build_all(inner, cfg)
        i_items, i_bytes = progress_mod.plan_totals(inner_bundle["plans"])
        bar.total_items += i_items
        bar.total_bytes += i_bytes
        bar.enabled = args.yes and bar.total_items > 1
        placed = 0
        for pl in inner_bundle["plans"]:
            if not pl.get("system"):
                unresolved.append(pl["name"])
                continue
            res = apply_mod.apply_plan(pl, dry_run=False, roots=roots,
                                       overwrite=args.overwrite,
                                       log=lambda *a: None, on_progress=tick)
            for made, kind in res.created:
                journal.add(made, kind)
            errors += len(res.errors)
            placed += 1
            manual.extend(f"[{pl['name']}] {s}" for s in apply_mod.manual_steps(pl))
        bar.finish()
        _p(f"  filed {placed} game(s) from the collection")
        shutil.rmtree(staging, ignore_errors=True)

    bar.finish(f"  {bar.items_done} file(s), "
               f"{progress_mod.human_bytes(bar.bytes_done)} in "
               f"{progress_mod.human_time(bar.elapsed)}" if bar.items_done else "")

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

    # 5. Optionally reclaim the drop folder now the games are filed.
    if args.clean:
        _p("\n[5/5] Reclaiming the drop folder")
        report = clean_mod.survey(sources, [cfg.rom_dir, cfg.install_dir],
                                  quick=args.quick_verify)
        if report.safe:
            removed, freed = clean_mod.purge(report, dry_run=not args.yes, log=_p)
            _p(f"  {removed} file(s), {freed / 1_073_741_824:.2f} GB"
               f"{'' if args.yes else ' (dry run)'}")
            if args.yes:
                clean_mod.prune_empty_dirs(sources, dry_run=False, log=_p)
        else:
            _p("  nothing to reclaim")
        for c in report.mismatched + report.unmatched:
            _p(f"  kept   {c.source.name}: {c.reason}")

    # Emulator suggestions: when the emulator in use needs a BIOS you lack,
    # another one in ES-DE's own list may not.
    es_dir = Path(cfg.es_config_dir)
    for key in sorted({pl.get("system") for pl in bundle["plans"] if pl.get("system")}):
        alt = emu_mod.suggest(key, es_dir)
        if alt:
            in_use = emu_mod.effective(key, es_dir)
            _p("")
            _p(f"{key}: {in_use.label} needs a BIOS you do not have.")
            _p(f"  {alt.label} plays the same games without one. To switch:")
            _p(f"    esdeck emulators --system {key} --emulator \"{alt.label}\" --yes")

    # BIOS: say so before the user wonders why a game will not start.
    bios_problems = []
    for key in sorted({pl.get("system") for pl in bundle["plans"] if pl.get("system")}):
        for w in bios_mod.warn_lines(key, es_config_dir=es_dir):
            bios_problems.append(f"{key}: {w}")
    if bios_problems:
        _p("\nBIOS needed - these will most likely not start yet:")
        for b in bios_problems:
            _p(f"  - {b}")
        _p("  esdeck does not download BIOS files (copyrighted firmware).")
        _p("  Run 'esdeck bios' for the exact filenames and folder.")

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
        if journal.created:
            history_mod.save(journal)
            _p(f"\nRecorded this sort - 'esdeck undo' reverses it "
               f"({journal.files} file(s)).")
        _p("\nDone. Restart ES-DE (or press F5 in it) to see the new games.")
    return 1 if errors else 0


# ---------------------------------------------------------------- emulators
def cmd_emulators(args) -> int:
    """Show or set which emulator ES-DE uses for a system."""
    cfg = config.load()
    es_dir = Path(cfg.es_config_dir)

    if args.system and args.emulator:
        if bootstrap.es_de_running():
            _p("ES-DE is running - it rewrites gamelist.xml on exit. Quit it first.")
            return 2
        available = {c.label for c in emu_mod.choices_for(args.system)}
        if available and args.emulator not in available:
            _p(f"ES-DE has no emulator called {args.emulator!r} for {args.system}.")
            _p("Choices: " + ", ".join(sorted(available)))
            return 2
        _p(emu_mod.set_emulator(es_dir, args.system, args.emulator,
                                dry_run=not args.yes))
        if args.yes:
            cfg.emulators[args.system] = args.emulator
            config.save(cfg)
            _p(f"Recorded in {config.CONFIG_PATH} - travels with 'esdeck profile'.")
        else:
            _p("DRY RUN. Re-run with --yes to apply.")
        return 0

    if args.apply:
        if bootstrap.es_de_running():
            _p("ES-DE is running - quit it first.")
            return 2
        _p(f"Applying {len(cfg.emulators)} recorded choice(s):")
        emu_mod.apply_choices(es_dir, cfg.emulators, dry_run=not args.yes, log=_p)
        if not args.yes:
            _p("")
            _p("DRY RUN. Re-run with --yes to apply.")
        return 0

    systems = [args.system] if args.system else sorted(
        d.name for d in Path(cfg.rom_dir).iterdir()
        if d.is_dir() and any(d.iterdir())) if Path(cfg.rom_dir).is_dir() else []
    for key in systems:
        options = emu_mod.choices_for(key)
        if not options:
            continue
        active = emu_mod.current(es_dir, key) or options[0].label + "  (ES-DE default)"
        _p(f"{key}: using {active}")
        for c in options:
            mark = "*" if c.label == emu_mod.current(es_dir, key) else " "
            _p(f"  {mark} {c.describe()}")
        s = emu_mod.suggest(key, es_dir)
        if s:
            _p(f"  -> suggestion: {s.label} avoids the BIOS this system needs")
            _p(f"     esdeck emulators --system {key} --emulator \"{s.label}\" --yes")
    return 0


# -------------------------------------------------------------------- clean
def cmd_clean(args) -> int:
    """Delete drop-folder copies that are verified present in the library."""
    cfg = config.load()
    sources = [Path(d) for d in cfg.source_dirs]
    if args.source:
        sources = [Path(args.source)]
    if not sources:
        _p("No drop folder configured. esdeck init --source-dir <path>")
        return 2

    roots = [cfg.rom_dir, cfg.install_dir]
    _p("Verifying drop-folder files against the library"
       + (" (size only)" if args.quick else " (full content hash)") + " ...")
    report = clean_mod.survey(sources, roots, quick=args.quick)

    removed = freed = pruned = 0
    if report.safe:
        _p("")
        _p(f"{len(report.safe)} file(s) safely in the library, "
           f"{progress_mod.human_bytes(report.reclaimable)} reclaimable:")
        removed, freed = clean_mod.purge(report, dry_run=not args.yes, log=_p)
    if report.mismatched:
        _p("")
        _p(f"{len(report.mismatched)} file(s) NOT removed - same name in the library "
           f"but different content:")
        for c in report.mismatched:
            _p(f"  keep   {c.source.name}")
    if report.unmatched:
        _p("")
        _p(f"{len(report.unmatched)} file(s) NOT removed - not in the library "
           f"(never sorted, or skipped as UNKNOWN):")
        for c in report.unmatched[:20]:
            _p(f"  keep   {c.source.name}")
        if len(report.unmatched) > 20:
            _p(f"  ... and {len(report.unmatched) - 20} more")

    if args.yes:
        pruned = clean_mod.prune_empty_dirs(sources, dry_run=False, log=_p)

    # The bottom line, always printed: how much was actually deleted and how
    # much room that gave back. Reading a wall of per-file lines to work that
    # out is exactly the sort of arithmetic a person should not have to do.
    kept = len(report.unmatched) + len(report.mismatched)
    _p("")
    _p("  " + "-" * 58)
    if args.yes:
        _p(f"   Files deleted:  {removed}")
        _p(f"   Space freed:    {progress_mod.human_bytes(freed)}")
        if pruned:
            _p(f"   Empty folders removed: {pruned}")
    else:
        _p(f"   Would delete:   {removed} file(s)")
        _p(f"   Would free:     {progress_mod.human_bytes(freed)}")
    _p(f"   Kept:           {kept} file(s) not verified in the library")
    _p("  " + "-" * 58)

    if not report.safe:
        _p("")
        _p("Nothing to reclaim - the drop folder holds nothing already in the library.")
    elif not args.yes:
        _p("")
        _p("DRY RUN - nothing deleted. Re-run with --yes to free the space.")
    return 0


# ------------------------------------------------------------------- drives
def cmd_drives(args) -> int:
    """List drives and how much room they have, for choosing where games live."""
    found = drives_mod.list_drives()
    if args.current:
        cfg = config.load()
        _p(str(Path(cfg.rom_dir).parent) if cfg.rom_dir else "")
        return 0
    if args.rom_dir:
        # --current gives the drive, which is what the setup questions are
        # about. This gives the folder games are actually in, which is what
        # someone means when they ask where their games are.
        cfg = config.load()
        _p(str(cfg.rom_dir) if cfg.rom_dir else "")
        return 0
    if args.normalize is not None:
        _p(drives_mod.normalize_target(args.normalize))
        return 0
    if args.suggest:
        _p(drives_mod.suggest())
        return 0
    if not found:
        _p("No fixed drives found.")
        return 1
    for d in found:
        marker = "->" if f"{d.letter}\\" in drives_mod.suggest() else "  "
        _p(f" {marker} {d.describe()}")
    _p("")
    _p(f"Suggested: {drives_mod.suggest()}")
    return 0


# ----------------------------------------------------------- release notes
def cmd_release_notes(args) -> int:
    """Print one version's changelog entry, for use as GitHub release notes.

    Release pages should carry the detail themselves - a link to CHANGELOG.md
    makes the reader go and find it. This prints exactly what belongs on the
    page:  gh release create vX --notes "$(esdeck release-notes X)"
    """
    source = Path(args.file) if args.file else Path("CHANGELOG.md")
    if not source.is_file():
        _p(f"No changelog at {source}")
        return 2
    text = source.read_text(encoding="utf-8")
    sections = {v: (d, b) for v, d, b in update_mod.split_sections(text)}
    version = args.version or __version__
    if version not in sections:
        _p(f"No entry for {version}. Found: {', '.join(list(sections)[:8])}")
        return 2
    date, body = sections[version]
    if date:
        _p(f"Released {date}")
        _p("")
    _p(body)
    return 0


# --------------------------------------------------------------------- icon
def cmd_icon(args) -> int:
    """Crop a picture to a circle and write a Windows .ico, then a shortcut."""
    src = Path(args.source)
    if not src.is_file():
        _p(f"No such image: {src}")
        return 2
    dest = Path(args.dest) if args.dest else src.with_suffix(".ico")
    try:
        side, out = icon_mod.make(src, dest)
    except icon_mod.IconError as exc:
        _p(f"Could not use {src.name}: {exc}")
        _p("Save it as a non-interlaced 8-bit PNG and try again.")
        return 2
    _p(f"Wrote {out}  ({side}x{side} source, corners made transparent)")

    if args.shortcut:
        target = Path(args.shortcut).resolve()
        link = _desktop() / f"{args.name}.lnk"
        if make_shortcut(link, target, out, log=_p):
            _p(f"Shortcut: {link}")
        else:
            _p("Could not create the shortcut.")
    return 0


def _desktop() -> Path:
    for candidate in (Path.home() / "OneDrive" / "Desktop", Path.home() / "Desktop"):
        if candidate.is_dir():
            return candidate
    return Path.home()


def make_shortcut(link: Path, target: Path, icon_path: Path | None = None,
                  *, log=print) -> bool:
    """A .lnk on the Desktop. Batch files cannot carry an icon; shortcuts can."""
    import subprocess
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath = '{target}';"
        "$s.WorkingDirectory = '{wd}';"
        "{icon}"
        "$s.Save()"
    ).format(link=str(link).replace("'", "''"),
             target=str(target).replace("'", "''"),
             wd=str(target.parent).replace("'", "''"),
             icon=(f"$s.IconLocation = '{str(icon_path).replace(chr(39), chr(39)*2)}';"
                   if icon_path else ""))
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"  {exc}")
        return False
    if proc.returncode != 0:
        log(f"  {(proc.stderr or proc.stdout).strip()[:200]}")
        return False
    return link.is_file()


# ------------------------------------------------------------------- update
def cmd_update(args) -> int:
    """Check GitHub for a newer esdeck, show what changed, and install it."""
    if args.check:
        found = update_mod.check(force=True)
        if found is None:
            _p("could not reach GitHub")
            return 2
        _p(f"installed {found.current}, available {found.version}")
        return 0 if found.newer else 1

    _p(f"ThuggyEmuAutomation {__version__} - checking for updates...")
    found = update_mod.check(force=True)
    if found is None:
        _p("  could not reach GitHub - carrying on with what is installed.")
        return 0
    if not found.newer:
        _p(f"  already up to date ({found.current}).")
        return 0

    _p("")
    _p(f"  Update available: {found.current}  ->  {found.version}")

    # Show what changed before asking. Every missed version is listed in
    # order, so being several behind explains itself rather than arriving as
    # one opaque jump.
    text = update_mod.fetch_changelog()
    sections = update_mod.changes_since(found.current, text) if text else []
    if sections:
        count = len(sections)
        _p("")
        _p(f"  {count} update{'s' if count > 1 else ''} since your version"
           f"{' - oldest first' if count > 1 else ''}:")
        _p(update_mod.format_changes(sections))
    elif text:
        _p("  (no changelog entries found for these versions)")
    else:
        _p("  (could not fetch the changelog)")

    if not args.yes:
        _p("")
        _p("  Re-run with --yes to install it.")
        # 10 means "there is an update, and it was not installed". The desktop
        # app runs this first to show the changelog, then asks; a plain 0 here
        # would be indistinguishable from already being current.
        return 10

    _p("")
    bat_dir = Path(args.bat_dir) if args.bat_dir else None
    if update_mod.download_and_install(bat_dir=bat_dir, log=_p):
        _p(f"  updated to {found.version}.")
        return 0
    _p("  update failed - the installed version still works.")
    return 1


# ------------------------------------------------------------------ cleanup
def cmd_cleanup(args) -> int:
    """Remove artwork an older esdeck filed as games, and tidy what is left."""
    cfg = config.load()
    rom_dir = Path(cfg.rom_dir)
    if not rom_dir.is_dir():
        _p(f"No ROM library at {rom_dir}")
        return 2

    _p(f"Checking {rom_dir} for artwork filed as games...")
    report = cleanup_mod.find_junk(rom_dir)

    if report.kept:
        _p("")
        for path, why in report.kept[:10]:
            _p(f"  keeping {path.name}: {why}")

    if not report.junk:
        _p("")
        _p("No artwork found in the library - nothing to remove.")
    else:
        _p("")
        _p(f"{len(report.junk)} image(s) filed as games, "
           f"{report.reclaimable / 1_048_576:.0f} MB:")
        by_system = {}
        for j in report.junk:
            by_system[j.system] = by_system.get(j.system, 0) + 1
        for sysname, count in sorted(by_system.items(), key=lambda kv: -kv[1]):
            _p(f"    {sysname:<16} {count} file(s)")
        _p("")
        removed, freed = cleanup_mod.remove(
            report, dry_run=not args.yes,
            log=_p if args.verbose else lambda *a: None)
        _p(f"  {removed} removed, {freed / 1_048_576:.0f} MB freed"
           f"{'' if args.yes else ' (dry run)'}")

    if args.yes:
        pruned = cleanup_mod.prune_empty(cleanup_mod.empty_dirs(rom_dir),
                                         dry_run=False, log=lambda *a: None)
        if pruned:
            _p(f"  {pruned} empty folder(s) removed")
        gone = cleanup_mod.systems_left_empty(rom_dir)
        junk_systems = [g for g in gone if g in ("pico8", "tic80")]
        if junk_systems:
            _p(f"  {', '.join(junk_systems)} now empty - ES-DE will stop listing them")

    # The rest of the tidying: one entry per game, duplicates, strays.
    _p("")
    _p("Library tidy:")
    fixes = tidy_mod.redundant_entries(rom_dir) + tidy_mod.unhidden_disc_folders(rom_dir)
    for path, why in fixes:
        _p(f"  hide   {path.name}  ({why})")
        if args.yes:
            apply_mod.set_hidden(path)
    if not fixes:
        _p("  each game already shows once")

    dupes = tidy_mod.duplicates(rom_dir)
    if dupes:
        _p("")
        _p(f"{len(dupes)} duplicate title(s) - not removed, your call which to keep:")
        for d in dupes[:15]:
            _p(f"  {d.describe()}")
        if len(dupes) > 15:
            _p(f"  ... and {len(dupes) - 15} more")

    if not args.yes:
        _p("")
        _p("DRY RUN - nothing was changed. Re-run with --yes to apply.")
    else:
        _p("")
        _p("Done. Press F5 in ES-DE to refresh.")
    return 0


# -------------------------------------------------------------- controller
def cmd_controller(args) -> int:
    """Show or fix which device RetroArch treats as player 1."""
    info = controller_mod.diagnose()
    if info["retroarch"] is None:
        _p("RetroArch not found - run esdeck.bat first.")
        return 2

    _p(f"RetroArch: {info['retroarch']}")
    _p("")
    _p("Controllers Windows reports through XInput (slot 0 becomes player 1):")
    if info["xinput_pads"]:
        for pad in info["xinput_pads"]:
            _p(f"  {pad.describe()}")
    else:
        _p("  none connected right now - plug the controller in first")
    if info["log_pads"]:
        _p("")
        _p("What RetroArch saw last time it ran:")
        for pad in info["log_pads"]:
            _p(f"  {pad.describe()}")

    _p("")
    _p("Current settings:")
    _p(f"  joypad driver      {info['joypad_driver']}")
    _p(f"  player 1 device    {info['player1_index']}")
    _p(f"  player 2 device    {info['player2_index']}")
    _p(f"  autodetect         {info['autodetect']}")

    if args.diagnose:
        return 0

    if bootstrap.retroarch_running():
        _p("")
        _p("RetroArch is running - it rewrites its config on exit. Quit it first.")
        return 2

    _p("")
    _p("Making the controller player 1:")
    try:
        changes = controller_mod.apply(info["cfg_path"], controller_mod.DESIRED,
                                       dry_run=not args.yes)
    except FileNotFoundError as exc:
        _p(f"  {exc}")
        return 2
    for c in changes:
        _p(f"  {c}")
    _p("")
    _p("The keyboard still works - it has its own bindings and is not a player.")
    if not args.yes:
        _p("")
        _p("DRY RUN. Re-run with --yes to apply.")
    return 0


# --------------------------------------------------------------------- undo
def cmd_undo(args) -> int:
    """Reverse a previous sort, removing only what that run created."""
    found = history_mod.runs()
    if not found:
        _p("No sorts recorded yet - nothing to undo.")
        return 0

    if args.run:
        match = [(p, r) for p, r in found if p.stem == str(args.run)]
        if not match:
            _p(f"No run with id {args.run}. Use 'esdeck history' to list them.")
            return 2
        path, run = match[0]
    else:
        path, run = found[0]

    _p(f"Undoing the sort of {run.when}")
    if run.sources:
        _p(f"  from: {', '.join(run.sources)}")
    _p(f"  it created {run.files} file(s), "
       f"{run.total_bytes / 1_048_576:.0f} MB")
    _p("")
    res = history_mod.undo(run, dry_run=not args.yes,
                           log=_p if args.verbose else lambda *a: None)
    _p(f"  {res.summary()}")
    for kept, why in res.kept[:10]:
        _p(f"  kept   {Path(kept).name}: {why}")
    if len(res.kept) > 10:
        _p(f"  ... and {len(res.kept) - 10} more kept")

    if not args.yes:
        _p("")
        _p("DRY RUN - nothing was removed. Re-run with --yes to undo.")
    else:
        history_mod.forget(path)
        _p("")
        _p("Your original files in the drop folder were never touched.")
    return 0


# ------------------------------------------------------------------ history
def cmd_history(args) -> int:
    """List previous sorts, newest first."""
    found = history_mod.runs()
    if not found:
        _p("No sorts recorded yet.")
        return 0
    _p(f"{'id':<12} {'when':<21} {'files':>7} {'size':>10}  sources")
    for path, run in found:
        _p(f"{path.stem:<12} {run.when:<21} {run.files:>7} "
           f"{run.total_bytes / 1_048_576:>9.0f}M  "
           f"{', '.join(Path(s).name for s in run.sources) or '-'}")
    _p("")
    _p("esdeck undo            reverse the most recent sort")
    _p("esdeck undo --run ID   reverse a specific one")
    return 0


# --------------------------------------------------------------------- tidy
def cmd_tidy(args) -> int:
    """Repair a library: one entry per game, and report duplicate copies."""
    cfg = config.load()
    rom_dir = Path(cfg.rom_dir)
    if not rom_dir.is_dir():
        _p(f"No ROM directory at {rom_dir}")
        return 2

    # A stray "G" folder from answering the drive question with a bare letter.
    # Look next to wherever tidy was run from, which is where it would land.
    strays = tidy_mod.stray_libraries(Path.cwd())
    if args.near:
        strays += tidy_mod.stray_libraries(Path(args.near))
    for st in strays:
        _p("  " + tidy_mod.remove_stray(st, dry_run=not args.yes))

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
        statuses = bios_mod.check_system(key, es_config_dir=Path(cfg.es_config_dir))
        if not statuses:
            continue
        blockers = bios_mod.blocking(statuses)
        problems += len(blockers)
        _p(f"{key}  {'PROBLEM' if blockers else 'ok'}")
        for st in statuses:
            if args.all or st.state != "missing (optional)":
                note = f"  ({st.bios.note})" if st.bios.note else ""
                _p(f"    {st.state:20} {st.bios.name}{note}")
        for w in bios_mod.warn_lines(key, es_config_dir=Path(cfg.es_config_dir)):
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
                missing.extend(bios_mod.blocking(bios_mod.check_system(
                    d.name, es_config_dir=Path(cfg.es_config_dir))))
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
    # Worth having: the .bat files are only launchers, so a fresh download does
    # not by itself update the code they run. This says what is actually installed.
    ap.add_argument("--version", action="version",
                    version=f"esdeck {__version__}  (installed at "
                            f"{Path(__file__).resolve().parent})")
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
    p.add_argument("source", nargs="*", help="one or more folders (default: configured)")
    p.add_argument("--json", help="also write the raw scan to this file")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("plan", help="build a reviewable install plan")
    p.add_argument("source", nargs="*", help="one or more folders (default: configured)")
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

    p = sub.add_parser("emulators", help="show or set the emulator ES-DE uses")
    p.add_argument("--system")
    p.add_argument("--emulator")
    p.add_argument("--apply", action="store_true",
                   help="apply every choice recorded in the config")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_emulators)

    p = sub.add_parser("clean", help="delete drop-folder copies already in the library")
    p.add_argument("source", nargs="*", help="one or more folders (default: configured)")
    p.add_argument("--yes", action="store_true", help="delete (default is a dry run)")
    p.add_argument("--quick", action="store_true",
                   help="verify by size only instead of hashing the contents")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("drives", help="show drives and free space")
    p.add_argument("--suggest", action="store_true",
                   help="print only the suggested folder, for scripts")
    p.add_argument("--current", action="store_true",
                   help="print the games folder this PC is already using")
    p.add_argument("--rom-dir", action="store_true",
                   help="print the folder the games library lives in")
    p.add_argument("--normalize", metavar="ANSWER",
                   help="turn a typed answer like 'G' into an absolute folder")
    p.set_defaults(func=cmd_drives)

    p = sub.add_parser("release-notes",
                       help="print a version's changelog entry for a release page")
    p.add_argument("version", nargs="?", help="defaults to the installed version")
    p.add_argument("--file", help="changelog to read (default CHANGELOG.md)")
    p.set_defaults(func=cmd_release_notes)

    p = sub.add_parser("icon", help="make a circular .ico from a picture")
    p.add_argument("source", help="a PNG to crop")
    p.add_argument("--dest", help="where to write the .ico")
    p.add_argument("--shortcut", help="also make a Desktop shortcut to this .bat")
    p.add_argument("--name", default="ThuggyEmuAutomation",
                   help="name for the shortcut")
    p.set_defaults(func=cmd_icon)

    p = sub.add_parser("update", help="check GitHub for a newer esdeck and install it")
    p.add_argument("--yes", action="store_true", help="install it, not just report")
    p.add_argument("--check", action="store_true",
                   help="exit 0 if an update exists, 1 if not, 2 if unreachable")
    p.add_argument("--bat-dir", help="also refresh the .bat files in this folder")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("cleanup", help="remove artwork an older esdeck filed as games")
    p.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    p.add_argument("--verbose", action="store_true", help="list every file")
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser("controller", help="make the game controller player 1")
    p.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    p.add_argument("--diagnose", action="store_true", help="report only, change nothing")
    p.set_defaults(func=cmd_controller)

    p = sub.add_parser("undo", help="reverse a previous sort")
    p.add_argument("--run", help="undo a specific run (see esdeck history)")
    p.add_argument("--yes", action="store_true", help="remove (default is a dry run)")
    p.add_argument("--verbose", action="store_true", help="list every file")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("history", help="list previous sorts")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("tidy", help="repair an existing library and find duplicates")
    p.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    p.add_argument("--near", help="also look here for stray mis-created library folders")
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
    p.add_argument("source", nargs="*", help="one or more folders (default: configured)")
    p.add_argument("--yes", action="store_true", help="actually do it (default is a dry run)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--system", help="force a system for every item")
    p.add_argument("--no-cores", action="store_true", help="skip the RetroArch core step")
    p.add_argument("--clean", action="store_true",
                   help="afterwards delete drop-folder copies verified in the library")
    p.add_argument("--keep-duplicates", action="store_true",
                   help="file every copy of a game, not just the best one")
    p.add_argument("--quick-verify", action="store_true",
                   help="with --clean, verify by size instead of hashing")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("check-setup",
                       help="exit 0 if this machine is configured usably")
    p.set_defaults(func=cmd_checksetup)

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
