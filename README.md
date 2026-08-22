# esdeck

Set up **ES-DE** (EmulationStation Desktop Edition) on a new Windows machine, and turn a folder of
handed-over games into a correctly-laid-out ROM library — without doing the busywork by hand on
every computer.

It does two jobs:

1. **Machine setup** — install ES-DE, RetroArch and emulators via `winget`, build the
   `ROMs/<system>/` tree, and carry your preferences to the next computer with a profile file.
2. **Game intake** — look at whatever you were given (bare ROMs, disc images, archives, PC
   installers), work out what each thing is, read the README when there is one, and produce a
   **plan you can read before anything is written**.

Zero dependencies — Python 3.10+ standard library only, so getting it onto machine number four is
`git clone` and nothing else.

## Install

```bash
git clone https://github.com/<you>/esdeck && cd esdeck && pip install -e .
```

Or skip installing entirely and run it in place with `python -m esdeck ...`.

## Quick start

```bash
esdeck init --rom-dir D:\ROMs
```

```bash
esdeck bootstrap --yes
```

```bash
esdeck plan D:\incoming
```

```bash
esdeck apply esdeck-plan.json --yes
```

```bash
esdeck link --yes
```

`plan` writes `esdeck-plan.json` and changes nothing. `apply` without `--yes` is a dry run. Only
`apply --yes` touches the disk.

## How intake works

Detection **never depends on a README existing.** Files are classified first — ROM, disc image,
archive, installer, doc, support — and the system is chosen by weighted vote:

| Signal | Weight |
| --- | --- |
| Unambiguous ROM extension (`.sfc`, `.n64`, …) | 5 |
| Installer present with no ROM anywhere → `windows` | 4 |
| Folder-name hint (`PSX Games/`, `Sony PlayStation 2/`) | 3 |
| README naming an emulator (PCSX2 → `ps2`) | 3 |

Ambiguous extensions (`.iso`, `.cue`, `.chd`, `.zip`) never decide anything on their own — they
record *candidates*. Each item comes out as `high`, `medium` or `low` confidence, and `esdeck scan`
shows you the reasoning:

```
OK   Super Mario World  ->  snes   (1 files, 1 MB)
?    Final Fantasy VII  ->  psx    (7 files, 1300 MB)
       also plausible: saturn, dreamcast, pcengine
       readme README.txt: flags: needs_bios; emulators: retroarch,duckstation
??   Some Unknown Game  ->  UNKNOWN
       also plausible: gc, ps2, ps3, psp, saturn, wii, windows
```

Force one with `esdeck plan <dir> --system ps2`, or just edit the JSON plan before applying.

Behaviour worth knowing:

- **Multi-disc sets** (`Game (Disc 1).cue`, `Disc 2`, …) get an `.m3u` playlist so ES-DE shows one entry.
- **Arcade/Neo Geo `.zip` files are copied, never extracted** — the zip *is* the ROM there.
- **A folder of loose ROMs** (`SNES Games/`) splits into one entry per game; a folder with a README,
  an installer, or a `.cue`+`.bin` set stays a single game.
- **Nothing is ever moved.** Sources are copied, and an existing destination file is left alone
  unless you pass `--overwrite`.

## READMEs are read, never obeyed

A README is untrusted text written by someone else. esdeck parses it for genuinely useful facts —
required BIOS files, disc count, emulator names, patch/serial/mount requirements, and any
command-looking lines — and turns them into **`needs_review` actions that `apply` refuses to
execute**:

```
Manual steps left for you (nothing below was executed):
  - [Final Fantasy VII] BIOS files referenced: scph1001.bin  [README.txt]
  - [Retro Racer] A serial/product key is required during install - enter it yourself.
  - [Retro Racer] Review before running (READ ME FIRST.txt:4): setup.exe /VERYSILENT /DIR="C:\Games"
```

Installers are surfaced with their path and target folder for you to run; esdeck will not launch
a third-party `setup.exe` for you, and it will not apply ROM patches.

Other safety properties, all covered by tests:

- Writes are confined to your configured ROM and install directories (`--unsafe-any-path` to opt out).
- Zip extraction rejects path traversal (zip-slip).
- Prose like `2. Run setup.exe` is recorded as a *step*, not as a command.

## Making ES-DE actually see the library

Two steps trip people up on every new machine, so esdeck does both:

**`esdeck link`** writes your ROM directory into ES-DE's own `es_settings.xml`.
ES-DE defaults to `~/ROMs`, so a library on another drive shows up as zero systems until
this is set. The edit is surgical - one attribute, every other line untouched, with a
one-time `.esdeck-backup` alongside. ES-DE rewrites that file when it exits, so `link`
refuses to run while ES-DE is open.

**`esdeck launchers`** solves the PC-game gap: ES-DE's `windows` system only accepts
`.bat` and `.lnk`, so a game installed into a folder is invisible no matter what is in it.
This finds the real executable - skipping `unins*`, `vcredist`, `dxsetup` and friends,
preferring shallow and obviously-named ones - and writes a small `.bat` that runs the game
from its own directory. When several executables are plausible it lists them and asks for
`--exe` rather than guessing.

```bash
esdeck launchers --yes
```

## Multiple computers

Machine-specific paths live in `~/.esdeck/config.json` and are never shared. Everything else
travels:

```bash
esdeck profile export --file esdeck-profile.json
```

On the next machine, after `esdeck init` and `esdeck bootstrap`:

```bash
esdeck profile import --file esdeck-profile.json
```

`esdeck doctor` then checks that machine: ROM directory present, ES-DE config found, ES-DE's own
`ROMDirectory` agreeing with esdeck's, `winget` available — each failure printed with its fix.

## Commands

| Command | What it does |
| --- | --- |
| `esdeck init` | Autodetect and record this machine's paths |
| `esdeck bootstrap` | Install ES-DE/RetroArch/emulators, create the ROM tree (dry run by default) |
| `esdeck scan <dir>` | Show what esdeck thinks each dropped game is, and why |
| `esdeck plan <dir>` | Write a reviewable `esdeck-plan.json` |
| `esdeck apply <plan>` | Execute the safe half of a plan (dry run by default) |
| `esdeck launchers` | Create `.bat` launchers so ES-DE can see installed PC games |
| `esdeck link` | Point ES-DE's own `ROMDirectory` at your esdeck library |
| `esdeck profile export/import` | Move settings between computers |
| `esdeck doctor` | Check this machine's setup |

## Tests

```bash
python -m unittest discover -s tests
```

## Scope

esdeck organises games **you already have** onto disk and configures the software that runs them.
It does not download, locate, or otherwise obtain games, BIOS files, or emulator firmware, and it
does not patch or modify game executables.

## License

MIT — see [LICENSE](LICENSE).
