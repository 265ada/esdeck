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

Clone the repo and double-click **`esdeck.bat`**. It asks where your games should
live, then installs and configures everything.

After that, **`sort-games.bat`** is the one you use: drag games onto it, or drop them
in your Incoming folder and double-click it.

**No git required.** On the repo page choose **Code -> Download ZIP**, extract it
anywhere, and double-click `esdeck.bat`. Once setup finishes you can delete the
extracted folder - esdeck is installed properly, not linked to it.

With git, if you have it:

```bash
git clone https://github.com/265ada/esdeck && cd esdeck && esdeck.bat
```

It asks one question - which drive your games should live on. It measures every
drive first and suggests the roomiest, but the choice is yours; nothing assumes a
D: drive exists:

```
 Your games can live on any drive. Here is what this PC has:

 -> D:    2873.9 GB free of   3726.0 GB
    C:     839.2 GB free of    930.5 GB  (system drive)

Suggested: D:\Games

  Game folder [D:\Games]: _
```

Then it does everything else:

| Step | What it does |
| --- | --- |
| Python | Installs it via winget if missing |
| esdeck | `pip install -e .` |
| Folders | Creates `<folder>\ROMs` (library) and `<folder>\Incoming` (drop zone) |
| Emulators | Installs ES-DE, RetroArch and 7-Zip via winget |
| ROM tree | Creates `ROMs\<system>\` for every supported system |
| ES-DE | Writes your ROM path into its settings so it finds the library |
| Cores | Downloads every core ES-DE actually launches (~80 cores, ~900 MB) |
| Shortcut | Puts **Sort Games** on your Desktop |
| Check | Runs `esdeck doctor` and prints any remaining problem with its fix |

Every step checks before it acts, so re-running it is safe.

For scripted or unattended installs, pass the folder as an argument:

```bash
esdeck.bat D:\Games --common-cores
```

Flags, in any order: `--common-cores`, `--no-cores`, `--all-emulators`,
`--repair`, `--clean` (free the drop folder afterwards), `--setup` (redo first-run setup).

## Daily use

Put games in `Incoming`, then double-click **esdeck** on the Desktop (put there on
first run), or run:

```bash
esdeck sync
```

`sync` is the one command: it reads the drop folder, files the games into the library,
fetches any missing cores, and creates launchers for PC games. It is a dry run that shows
you everything it would do; add `--yes` to actually do it.

## How intake works

Detection **never depends on a README existing**, and it does not trust file extensions
further than it should. ES-DE maps `.cue` to 73 different systems and `.bin` to 122, so an
extension is often nearly meaningless.

**Disc images are identified by reading them.** Every console stamps a signature in its
boot area, so esdeck opens the image and looks:

| Signature | System |
| --- | --- |
| `PLAYSTATION` + `BOOT=` in SYSTEM.CNF | `psx` |
| `PLAYSTATION` + `BOOT2=` in SYSTEM.CNF | `ps2` |
| `SEGA SEGASATURN` / `SEGA SEGAKATANA` / `SEGADISCSYSTEM` | `saturn` / `dreamcast` / `megacd` |
| magic `C2339F3D` at 0x1C, `5D1C9EA3` at 0x18 | `gc` / `wii` |

A `.cue` is followed to the `.bin` it points at. CHD files stay ambiguous on purpose - the
payload is compressed and identifying it would need `chdman`, so esdeck asks rather than
guesses.

Where the contents cannot decide, a weighted vote does:

| Signal | Weight |
| --- | --- |
| Disc signature read from the image | 8 |
| Unambiguous ROM extension (`.sfc`, `.n64`) | 5 |
| Extension claimed by 2-3 systems, most common first | 4 |
| Installer present with no ROM anywhere -> `windows` | 4 |
| Folder-name hint (`PSX Games/`, `Sony PlayStation/`) | 3 |
| README naming an emulator (PCSX2 -> `ps2`) | 3 |

Ties break by how common a system is, never alphabetically - ES-DE ships both a `doom` and a
`dos` system, and a DOS game should not land in `doom` because `d-o-o` sorts first.

### All 195 ES-DE systems

esdeck reads ES-DE's own `es_systems.xml` for the list of systems and the extensions each
accepts, so it covers everything the installed ES-DE covers, including systems added by
later ES-DE releases and anything you define in `custom_systems/`.

That table is used for *coverage*, not for precision: it is deliberately permissive (it
lists `.sfc` under `gb` and `gbc`), so a small curated table takes priority where it knows
which system actually owns an extension. Extensions the curated table has never heard of -
`.vpk`, `.wua`, `.dosz` and the rest - resolve through ES-DE's table.

Behaviour worth knowing:

- **One entry per game, not per file.** ES-DE lists every file whose extension a system
  claims, and `psx` claims `.bin`, `.cue` *and* `.m3u` - so a four-disc game would appear
  nine times. esdeck puts the discs in a subfolder, writes the `.m3u` beside it, and marks
  the subfolder hidden; single-disc games get the `.bin` hidden next to its `.cue`. This
  needs ES-DE's `ShowHiddenFiles` off, which `esdeck link` sets for you.
- **Multi-disc sets get an `.m3u`** so ES-DE shows one entry. This works whether the discs are
  files in one folder or, as they usually arrive, four sibling folders named
  `Game (USA) (Disc 1)` … `(Disc 4)` - those are merged into a single game.
- **Every archive format is handled** - `.zip`, `.7z`, `.rar`, `.cab`, `.tar`, `.gz`, `.xz`
  and the rest - through 7-Zip, which `esdeck.bat` installs. Archives are opened during
  scanning too, so a game inside a `.7z` is identified without unpacking it first, README
  included.
- **A collection is unpacked, then sorted game by game.** An archive holding many
  games is extracted to a staging folder, every game inside is identified and filed
  individually, and the staging folder is removed - so a 3259-ROM set becomes 3259
  library entries, not one unplayable one.
- **Split archives are one game, not fifty.** `Collection.part01.rar` through `.part47`,
  `Game.7z.001`, `Game.zip.001`, `Game.r00` and bare `.part01` sets are all recognised;
  only the first volume is opened and 7-Zip joins the rest.
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

## Which core gets installed

ES-DE runs the **first** `<command>` listed for a system in its `es_systems.xml`, so that
is the core that has to be present. esdeck reads it from there rather than guessing.

This matters more than it sounds: a hand-written map had `psx` on SwanStation while ES-DE
calls Beetle PSX, which fails at launch with *"couldn't find emulator core file
'mednafen_psx_libretro.dll'"*. Reading ES-DE's own configuration also found 59 systems a
hand-written map had missed entirely.

Cores ES-DE names but libretro does not build for Windows are skipped rather than retried
into a 404.

## Mods and ROM hacks

A patch file next to a ROM is applied automatically:

```
  copy   Zelda (USA).sfc -> ROMs\snes\Zelda (USA).sfc
  mod    Randomizer v3.ips -> Zelda (USA) (Randomizer v3).sfc
         IPS, base ROM verified
```

IPS, BPS and UPS are supported. The result is written as a **new** file, so the
unmodified game stays playable, and the original is never altered. BPS and UPS
record a checksum of the ROM they were built for; esdeck verifies it and refuses
rather than producing a subtly broken game. xdelta is still a manual step.

## Several drop folders

`scan`, `plan`, `sync` and `clean` all take any number of folders:

```bash
esdeck sync D:\Incoming E:\Downloads\Games "F:\Old PC\ROMs" --yes
```

Or record them once so a bare `esdeck sync` covers them all:

```bash
esdeck init --source-dir D:\Incoming --source-dir E:\Downloads\Games
```

## BIOS files

Some systems will not run without console firmware - Saturn, Dreamcast, Mega CD,
PS2 and others. **esdeck does not download BIOS files.** They are copyrighted
firmware, which is why RetroArch's own Online Updater fetches cores, shaders and
databases but deliberately not BIOS either.

What esdeck does instead is remove the guesswork. Drop a game in and it tells you
before you wonder why it will not start:

```
OK   Panzer Dragoon  ->  saturn  (2 files, 512 MB)
       BIOS: needs BIOS sega_101.bin or mpr-17933.bin in C:\RetroArch-Win64\system
             - without it this game will most likely not start
```

The requirements are read from **RetroArch's own core info files**, which declare
each core's firmware with its filename, whether it is optional, and often an md5.
That keeps it universal and current: it covers whatever cores are installed rather
than a list baked into esdeck. `esdeck bios` reports every system, and verifies the
files you supply by checksum so a bad dump is caught as `WRONG FILE` rather than
failing mysteriously at launch.

Optional firmware is not nagged about - a PS1 game runs fine without a BIOS, so
esdeck stays quiet about it.

## Reclaiming the drop folder

esdeck copies rather than moves, so a bad sort never loses anything - but that means a
game briefly exists twice, and a four-disc PSX game is 2.2 GB in each place.

```bash
esdeck clean
```

That lists what could be freed and deletes nothing. `--yes` removes the drop-folder copies,
but only files it has **verified byte for byte** against the library first: a full SHA-256
of both copies, not a name or size match. Anything that does not match, or is not in the
library at all, is kept and reported. `esdeck sync --clean` folds it into a normal run.

Deleting game files is the most destructive thing esdeck does, so it is opt-in, dry-run by
default, and never touches a file it has not proved is already safe elsewhere.

## Repairing an existing setup

`esdeck tidy` also removes a stray library folder created by answering the drive
question with a bare letter - an empty `G\ROMs` tree sitting next to the script.
It runs on every `esdeck.bat`, so such a folder cleans itself up. One that has real
files in it is reported rather than deleted.

`esdeck tidy` fixes a library built by hand, by another tool, or before these rules
existed: it hides the data half of multi-file games so each game shows once, and
reports duplicates - the same title in two formats, or filed under two systems. It
never deletes a game; which copy to keep is your call.

`esdeck.bat --repair` reinstalls ES-DE, RetroArch and 7-Zip over an existing
install. It uses winget's `--force` rather than uninstalling first, and backs up
your RetroArch saves, save states, controller bindings, playlists and `system/`
folder plus your ES-DE settings to a timestamped folder beforehand. An existing
install is otherwise detected and reused - it does not block or hang setup.

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
| `esdeck.bat` | The one file: sets up a new PC, then sorts games on every run |
| `esdeck emulators` | Show or set which emulator ES-DE uses, with BIOS-free suggestions |
| `esdeck sync` | Sort the drop folder and finish the setup (the usual command) |
| `esdeck init` | Autodetect and record this machine's paths |
| `esdeck bootstrap` | Install ES-DE/RetroArch/emulators, create the ROM tree (dry run by default) |
| `esdeck scan <dir>` | Show what esdeck thinks each dropped game is, and why |
| `esdeck plan <dir>` | Write a reviewable `esdeck-plan.json` |
| `esdeck apply <plan>` | Execute the safe half of a plan (dry run by default) |
| `esdeck drives` | Show drives and free space, and the suggested library location |
| `esdeck bios` | Report which BIOS files your systems need and verify the ones you have |
| `esdeck clean` | Free space: delete drop-folder copies verified present in the library |
| `esdeck tidy` | Repair an existing library and find duplicate copies |
| `esdeck cores` | Install RetroArch cores (`--all`, `--common`, or just what your systems need) |
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

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
