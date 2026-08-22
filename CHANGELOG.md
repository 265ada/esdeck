# Changelog

All notable changes to esdeck. Newest first.

The recurring theme: wherever esdeck had an opinion baked into a table, reading
ES-DE's or RetroArch's own configuration instead turned out to be both more
correct and more complete.

## [0.5.1] - 2026-08-22

### Fixed
- **Deleting the extracted ZIP folder uninstalled esdeck.** Setup used an
  editable install (`pip install -e .`), which only points at the folder it was
  run from - so tidying up the download afterwards left nothing behind. It now
  installs a real copy, and the extracted folder can be deleted once setup has
  finished.

## [0.5.0] - 2026-08-22

### Changed
- **Two files with one job each.** `esdeck.bat` sets a PC up - asks where games
  should live and installs everything needed. `sort-games.bat` sorts games, and
  accepts games or folders **dragged onto it** as well as reading the Incoming
  folder. Setup finishes by putting sort-games on your Desktop.

### Fixed
- **A broken config made setup skip itself forever.** "Already set up" was
  decided by whether config.json existed. A config left by an earlier version
  could point at a relative path like `G\ROMs`, so setup never re-ran, the
  Incoming folder was never created, and every run reported "No ROM directory"
  and sorted nothing. Setup is now decided by whether the config is *usable* -
  new `esdeck check-setup` - so a bad one sends you back through the question
  and repairs itself.
- **A corrupt config.json crashed with a Python traceback** in front of someone
  who double-clicked a .bat. It now falls back to autodetection, and reports
  the problem in a sentence.
- **A config copied from another PC kept that PC's user folder** for ES-DE, so
  every check failed against a path that does not exist here. Setup now detects
  this machine's own ES-DE location when the configured one is missing.

## [0.4.2] - 2026-08-22

### Fixed
- **esdeck.bat died instantly on any machine that downloaded it from GitHub**,
  with "The system cannot find the batch label specified - sort". Git was
  configured to normalise line endings, so the committed file - and therefore
  the ZIP download - was LF only, and cmd.exe cannot resolve `goto` in a batch
  file without CRLF. It worked locally because checkout converted the endings
  back, which is exactly why it went unnoticed. `.gitattributes` now marks
  `*.bat` as `-text`, so the bytes in the repo are the bytes you download.
- **Batch windows no longer close on their own.** Every exit path waits for a
  key, so an error can actually be read instead of vanishing with the window.
  `--no-pause` opts out for scripted runs.

## [0.4.1] - 2026-08-22

### Fixed
- **The stray "G" folder is now cleaned up, not just reported.** `esdeck tidy`
  removes a mis-created library folder left by answering the drive question with
  a bare letter, and `esdeck.bat` runs tidy on every run, so it disappears by
  itself on the next run - on any drive letter, on any PC. A stray that has real
  files in it is never deleted: by then it is somebody's library, wrong place or
  not, so it is reported with its file count instead.

## [0.4.0] - 2026-08-22

### Added
- **Mods are applied, not just flagged.** IPS, BPS and UPS patches sitting next
  to a ROM are applied automatically, written as a new file so the unmodified
  game stays playable. BPS and UPS record a checksum of the ROM they were built
  for and it is verified first - patching the wrong dump produces a game that
  looks fine and breaks hours later.
- **Several drop folders at once.** `scan`, `plan`, `sync` and `clean` take any
  number of folders, and `esdeck init --source-dir` can be repeated. Overlapping
  paths are collapsed so nothing is sorted twice.
- **`sort-games.bat`** for when you only want the sorting, without the setup.

### Fixed
- **Answering the drive question with just "G" created a folder called G** next
  to the script instead of using the G: drive - the prompt lists drives as "G:",
  so a bare letter is the natural answer. Any of `G`, `G:`, `G:\` or a full path
  now resolves correctly, a relative answer is refused outright, and a stray
  folder left by the old behaviour is pointed out.
- **Running esdeck.bat a second time re-ran the whole installer and failed.**
  Setup was gated on `doctor` exiting 0, but doctor reports a missing BIOS as a
  problem - which is normal - so every later run went back through the
  installer, and from the Desktop copy `pip install` had no project to install.
  Setup now checks whether esdeck is importable and configured, and refuses
  clearly if run somewhere it cannot install from.

## [0.3.0] - 2026-08-22

### Added
- **Collections are unpacked and sorted game by game.** A 3259-ROM Mega Drive
  set was being filed as one unplayable library entry. An archive holding many
  games is now extracted to a staging folder, each game inside is scanned and
  filed on its own, and the staging folder is removed. Verified on a real
  2.2 GB 47-part set: 3250 individual games.
- **`esdeck.bat`** - one file that does everything. On a new PC it installs and
  configures the whole setup; after that it sorts the Incoming folder. Replaces
  `install.bat` and `Sort Games.bat`.
- **`esdeck emulators`** - show or set which emulator ES-DE uses per system, and
  suggest a BIOS-free alternative when the one in use needs firmware you do not
  have. Suggestions now appear during `esdeck sync`.
- **SwanStation is the default for PSX**, because ES-DE's default (Beetle PSX)
  marks three BIOS files as required while SwanStation marks all of its firmware
  optional. The choice is stored in esdeck's config, so `esdeck profile` carries
  it to every other machine.
- This changelog.

### Fixed
- **A collection of 3259 ROMs plus one stray `.exe` was filed under Windows.**
  The installer vote fired on the mere presence of an executable; it now looks
  at what an archive is mostly made of, and at whether it contains any games at
  all.
- **A game whose title contains a system word no longer escapes its folder.**
  "Phantasy Star 3 - Generations of Doom" went to `doom`, "Arrow Flash" to
  `flash`, "Censor C64 Picture Demo" to `c64`. Where a game sits now outranks
  what it is called, and a README naming an emulator counts as an explicit
  statement of intent.
- BIOS checks follow the emulator actually in use rather than ES-DE's default,
  so choosing SwanStation stops the PSX BIOS warning instead of leaving it
  showing for a core that will never run.

## [0.2.0] - 2026-08-22

### Added
- **Every archive format** via 7-Zip: `.zip .7z .rar .cab .arj .lzh .tar .gz .xz
  .zst .wim` and more. Archives are opened during scanning, so a game inside a
  `.7z` is identified - and its README read - without unpacking.
- **Split archives** (`Game.part01.rar` .. `.part47`, `.7z.001`, `.zip.001`,
  `.r00`, bare `.001`) are one game, not fifty. Only the first volume is opened;
  7-Zip joins the rest. Reported size sums every volume.
- **`esdeck clean`** frees the drop folder after sorting, deleting only files
  proved identical to the library copy by full SHA-256. Dry run by default.
- **`esdeck bios`** reports the firmware each system needs, verifies supplied
  files by checksum, and warns at scan time so a game is never mysteriously
  dead. Requirements come from RetroArch's core info files.
- **`esdeck tidy`** repairs a library built by hand or by another tool, and
  reports duplicate copies without ever deleting a game.
- **`esdeck drives`** measures every drive and suggests where the library should
  live, instead of assuming `D:`.
- **`--repair`** reinstalls ES-DE/RetroArch over an existing install using
  winget `--force`, backing up saves, states, bindings, playlists and `system/`
  first. Uninstalling would have taken all of those with it.

### Changed
- Cores now come from ES-DE's own launch commands. A hand-written map had `psx`
  on SwanStation while ES-DE calls Beetle PSX, which failed with "couldn't find
  emulator core file". Fixed 11 wrong mappings and added 59 missing systems:
  155 systems, 81 cores.
- Every core is installed on first run. Previously a fresh machine got none,
  because the "which cores do my systems need" question answers "none" when the
  library is still empty.
- One ES-DE entry per game. ES-DE lists every file whose extension a system
  claims, and `psx` claims `.bin`, `.cue` and `.m3u` alike, so a four-disc game
  appeared nine times. Discs now live in a hidden subfolder behind their `.m3u`.

### Fixed
- Cores ES-DE names but libretro does not build for Windows are skipped rather
  than requested and 404ing.
- `link --create` writes the element type ES-DE expects; `ShowHiddenFiles` is a
  `<bool>`, and as a `<string>` it was silently ignored on fresh installs.

## [0.1.0] - 2026-08-22

### Added
- Initial release: `scan` / `plan` / `apply` pipeline that classifies dropped
  files, reads READMEs without obeying them, and files games into
  `ROMs/<system>/` for ES-DE.
- Disc images identified by reading their boot signature rather than trusting
  an extension - ES-DE maps `.cue` to 73 systems and `.bin` to 122.
- Multi-disc games merged into one entry with an `.m3u`, including the common
  case of four sibling `(Disc N)` folders.
- System list read from ES-DE's `es_systems.xml`, covering all 195 systems.
- `bootstrap` installs ES-DE, RetroArch and 7-Zip via winget; `link` points
  ES-DE at the library; `launchers` makes installed PC games visible.
- `profile export/import` carries settings between computers without carrying
  machine-specific paths.
- README-derived instructions become reviewable actions that `apply` refuses to
  execute, and writes are confined to the configured library folders.
