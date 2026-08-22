"""esdeck command line.

    esdeck init            configure this machine (paths, autodetect)
    esdeck bootstrap       install ES-DE + emulators, create the ROM tree
    esdeck scan <dir>      show what esdeck thinks each dropped game is
    esdeck plan <dir>      write a reviewable plan.json
    esdeck apply <plan>    execute the safe half of a plan
    esdeck profile         export/import machine-independent settings
    esdeck doctor          check this machine's setup
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import apply as apply_mod
from . import bootstrap, config, plan as plan_mod, scan as scan_mod
from .systems import BY_KEY

DEFAULT_PLAN = "esdeck-plan.json"


def _p(*a, **kw):
    print(*a, **kw)


# --------------------------------------------------------------------- init
def cmd_init(args) -> int:
    cfg = config.load() if config.CONFIG_PATH.is_file() and not args.force else config.discover()
    if args.rom_dir:
        cfg.rom_dir = str(Path(args.rom_dir).expanduser())
    if args.es_config_dir:
        cfg.es_config_dir = str(Path(args.es_config_dir).expanduser())
    if args.install_dir:
        cfg.install_dir = str(Path(args.install_dir).expanduser())
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
    bootstrap.run(cfg, packages=pkgs, dry_run=not args.yes, log=_p)
    if not args.yes:
        _p("\nRe-run with --yes to actually install.")
    return 0


# --------------------------------------------------------------------- scan
def _describe(item) -> None:
    conf = {"high": "OK  ", "medium": "?   ", "low": "??  "}[item.confidence]
    sysname = item.system or "UNKNOWN"
    _p(f"{conf} {item.name}  ->  {sysname}  ({len(item.files)} files, "
       f"{item.total_size / 1_048_576:.0f} MB)")
    if item.candidates:
        _p(f"       also plausible: {', '.join(item.candidates)}")
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


def cmd_scan(args) -> int:
    items = scan_mod.scan(Path(args.source))
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
    items = scan_mod.scan(Path(args.source))
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
    p.add_argument("--force", action="store_true", help="re-autodetect, discard existing config")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("bootstrap", help="install ES-DE/emulators and create the ROM tree")
    p.add_argument("--packages", nargs="*", help=f"subset of {', '.join(bootstrap.PACKAGES)}")
    p.add_argument("--all-emulators", action="store_true")
    p.add_argument("--yes", action="store_true", help="actually install (default is a dry run)")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("scan", help="identify dropped games")
    p.add_argument("source")
    p.add_argument("--json", help="also write the raw scan to this file")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("plan", help="build a reviewable install plan")
    p.add_argument("source")
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

    p = sub.add_parser("profile", help="share settings between computers")
    p.add_argument("action", choices=("export", "import"))
    p.add_argument("--file")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("doctor", help="check this machine's setup")
    p.set_defaults(func=cmd_doctor)
    return ap


def main(argv=None) -> int:
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
