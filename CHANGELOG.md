# Changelog

All notable changes to esdeck. Newest first.

The recurring theme: wherever esdeck had an opinion baked into a table, reading
ES-DE's or RetroArch's own configuration instead turned out to be both more
correct and more complete.

## [0.21.0] - 2026-08-28

### Fixed
- **A PC that was never set up looked set up.** The window showed a games
  folder and offered every action, because when no configuration exists esdeck
  falls back to autodetecting somewhere plausible. `C:\Users\<you>\ROMs` was a
  guess presented as a fact. Choosing *Sort games* then failed on a missing
  drop folder - a true and useless answer, since the missing step was the setup
  nobody had run.

  Being configured now means a configuration file exists, naming both a games
  library and a drop folder. Half a config counts as not configured: one that
  names a library but nowhere to drop games leaves every action failing on a
  missing folder, which is a worse place to stop than the beginning.

- **Sorting, fixing, undoing and freeing space now offer to set the PC up**
  rather than running into the wall. If it has not been set up they say so and
  ask whether to do it now, which is the step that was actually needed.

- **The advice named a drive from someone else's machine.** The failure
  suggested `esdeck init --source-dir D:\Games\Incoming` on a PC with no D:
  drive - the path was written into the message rather than worked out. It is
  now derived from the drive the library is already on, so it can be followed.

### Added
- **Setting up now proves it worked.** The check that runs at the end covers
  what was previously assumed:

  - a configuration was actually written, rather than guessed
  - a drop folder is configured, and exists
  - RetroArch is installed
  - every emulator core is present, counted against what ES-DE asks for

  Anything missing is reported as FAIL with the command that fixes it. A setup
  that installed nothing used to pass this check on autodetected guesses and
  report no problems, which is how a PC with nothing on it came to look
  healthy.

## [0.20.1] - 2026-08-23

### Changed
- **"Set up this PC" now says what it does on a PC that is already set up.**
  Running it again was always safe - it has never rewritten the configuration
  or moved a library on a machine that had one, because the question about
  which drive, and the step that acts on the answer, only happen when nothing
  has been configured. But the button reads like something that undoes a setup
  that already works, and nothing said otherwise.

  On a machine that is already set up it now explains itself first: that it
  installs anything missing, downloads any cores you do not have, re-checks the
  settings and the controller, and does not touch your games or move your
  library - naming the library so you can see which one it means.

  This is the answer to a PC set up by an older version with only a handful of
  emulator cores: run it again. No separate repair button, because a second
  button doing the same work is one more thing to explain and to get wrong.

## [0.20.0] - 2026-08-23

### Added
- **The install reports progress and an estimate, like the sorting does.**
  Fetching every emulator core is eighty downloads and several minutes, and it
  used to pass in silence. It now shows a bar, a count, which core is being
  fetched and how long is left. A core is counted when it has finished, not
  when it starts - counting it early makes the estimate run ahead of the truth.

- **Each step says which one it is, and how many there are.** The activity
  strip reads "Step 4 of 7: downloading emulator cores" rather than leaving a
  long install shapeless. The stage names say what is happening -
  "installing ES-DE and RetroArch", "making the pad player one" - because
  `cores --all --yes` is the honest label but not the thing anyone is waiting
  for.

- Installing packages counts them too, so a slow winget install says which of
  how many it is working through.

### Fixed
- Nothing was wrong with the GameCube folder or the cores, but both are now
  pinned by tests so they cannot drift:

  - The folder must be `gc`, which is what ES-DE looks for. Filed under
    `gamecube` it would simply never appear, with no error to explain why. The
    same trap exists for `psx` and not `ps1`, `megadrive` and not `genesis`,
    and eight more, all now checked - along with every folder esdeck sorts
    into, against ES-DE's own definitions, whenever ES-DE is installed.
  - `.iso` is deliberately *not* claimed by GameCube: it belongs equally to
    Wii, PS2 and Saturn, so it is decided by reading the disc header instead.
    A test covers a GameCube and a Wii disc being told apart that way.

  Checked against this machine: all 80 cores ES-DE's own definitions call for
  are installed, none missing, and all 32 folders esdeck files into are names
  ES-DE detects. The 44 remaining systems - Android, Kodi, Steam, ports - do
  not use libretro cores at all, which is correct rather than a gap.

## [0.19.1] - 2026-08-23

### Changed
- The drive question now offers removable drives too, and names each volume.
  An external drive is an ordinary place to keep a collection this size, and
  listing only internal ones would have hidden the very drive someone bought
  for the job. A removable drive is never chosen as the default, though - it
  can be unplugged, and a library that disappears is worse than a smaller one
  that stays put.

## [0.19.0] - 2026-08-23

### Fixed
- **"Set up this PC" never actually configured the PC.** It installed ES-DE,
  RetroArch and the cores, and then stopped short of the thing that makes them
  usable: it never wrote a configuration and never made a folder. So the window
  went on saying "No games folder configured yet" after a setup that had
  apparently succeeded, and there was nowhere to put a game.

  Setup now begins by asking one question - which drive - and does everything
  else itself: writes the configuration, creates the games library and the drop
  folder, installs ES-DE and RetroArch, fetches every core, maps the emulators,
  makes the pad player one, and finishes by telling you where to drop games.

  The question is asked only on a machine that has never been set up. Running
  it again is a repair, and a repair must not move anyone's library.

- **A guessed path was being mistaken for a configured one.** esdeck can always
  autodetect somewhere plausible for games to live, so asking it where they go
  always got an answer - which meant a brand new PC looked configured and was
  never asked. It is now asked whether anyone actually *chose*, which is the
  only thing that distinguishes the two.

### Added
- The drive question lists every fixed drive with its free space and preselects
  the one with the most room, which is what a collection of this size needs and
  is right far more often than wherever Windows happens to be installed.

## [0.18.0] - 2026-08-23

### Fixed
- **Finding Python on a PC that has never been set up.** Two things defeated
  looking on PATH, and both are normal on a fresh Windows 11 machine.

  Windows ships a stub called `python.exe` that does nothing but open the
  Microsoft Store. Finding that name told us nothing about whether Python was
  there, and using it fails in a way that looks like Python is broken. The
  check now insists on hearing a version number back before believing it.

  And a Python that winget installed a moment ago is not on this application's
  PATH, because that was captured when the application started - so its own
  successful install looked like a failure, and the advice was to go away and
  come back. It now also looks where installers actually put Python:
  `Programs\Python`, `Program Files`, and the newer install manager's
  `pythoncore-3.14-64` style folders.

- **Installing into a system-wide Python.** Where Python was installed for all
  users, this account cannot write to it and pip refuses. That is now retried
  as an install for the current user only, which always can.

### Changed
- The .exe genuinely stands alone: it needs no source zip and no unzipping.
  Given a PC with nothing on it, it finds or installs Python, installs esdeck
  itself, and gets on with the job. Python is still a real installation on the
  machine rather than something hidden inside the .exe - that is deliberate, it
  is what makes updates and repairs possible - but nothing is asked of you.

## [0.17.0] - 2026-08-23

### Fixed
- **"No module named esdeck" - every step failing, nothing installed.** This
  was a regression introduced in 0.15.0 and it is my fault. That release told
  Python to ignore the working directory when importing, to stop a stray copy
  of the source shadowing the installed package. On a PC where esdeck had never
  been pip-installed, that adjacent source folder *was* the only copy - so the
  change made it invisible, and every action failed identically. No ES-DE, no
  RetroArch, no cores, no games folder: all of it followed from that one line.

  **The application now installs its own prerequisites.** Before running
  anything it checks for Python and installs it through winget if it is
  missing, then checks that esdeck can actually be imported and installs it if
  not - from the folder beside the .exe when there is one, and straight from
  GitHub when there is not. Nothing has to be downloaded or unzipped by hand.
  If it cannot fix things it says which part failed and what to do, rather than
  repeating the same error five times.

- **Console windows stopped appearing.** Nine places started a program - 7-Zip,
  winget, tasklist, pip, powershell - and none of them suppressed the window. A
  process with no console of its own is given a *new* console for each console
  child, so these appeared over whatever you were doing, and one could be closed
  mid-extraction by a stray click. That is the thing the application existed to
  prevent. Every one now goes through a single helper that passes
  CREATE_NO_WINDOW, and a test fails the build if a new call site skips it.

- **The background fills the window again.** It was being fitted inside the
  window rather than covering it, and the artwork is tall where the window is
  not - so it sat as a narrow strip down the middle with dead space either
  side. It is now scaled to cover and cropped, the way a wallpaper should be.

### Added
- **A log of every run, and a button to export the lot.** Each command writes a
  transcript as it happens - the same text that appeared on screen, timestamped
  and kept - including the runs nobody is watching. When something comes out
  wrong afterwards, the question is always "what did it actually do", and that
  deserves a record rather than a memory of a window that has since scrolled
  away.

  *Export logs* bundles every run into a single zip, with a summary of what is
  in it. `esdeck logs` lists them; `esdeck logs --export` does the same from the
  command line. The last sixty runs are kept.

  Status lines are unrolled on the way into the file: a progress bar redrawing
  itself in place is one line on screen and an unreadable smear in a text file.

- **Each run says which button started it.** The transcript now opens with the
  name of the action and the time it began, so a log read later - or a bundle
  sent on for someone else to read - identifies itself instead of starting
  mid-thought.

## [0.16.0] - 2026-08-23

### Fixed
- **Artwork named like artwork is now removed, whatever folder it landed in.**
  A PICO-8 system listing "007 - The World Is Not Enough-image" and forty more
  like it survived every clean, because the check asked what a file *was* and
  a scraped PNG looks exactly like a PICO-8 cartridge, which really is a PNG.
  It now also asks what a file is *called*: anything ending in `-image`,
  `-marquee`, `-titlescreen`, `-video`, `-manual` and the rest of ES-DE's
  scraper names is artwork, whatever extension it wears, and is never spared as
  a cartridge. A genuine cartridge is still kept on the strength of its
  contents.

- **The system itself now goes away.** Deleting the files was never enough.
  ES-DE lists a system because its folder exists, and describes its contents
  from a gamelist it keeps separately - so an emptied system stayed on screen,
  still full of entries, with every file behind them gone. The emptied folder,
  its stale gamelist, and any scraped artwork left stranded are now removed
  together.

  Guarded, though: if *no* system has any games, that is a library which is
  missing rather than empty - an unplugged drive, a path typed wrong - and
  nothing is touched. Otherwise a wrong path would delete every gamelist and
  all the scraped artwork for a collection that is perfectly fine.

- **"Press F5" was the wrong advice.** F5 reloads one system; it cannot remove
  one, because ES-DE builds that list once at startup. Being told to press F5
  and then watching a dead system sit there is worse than being told nothing.
  When a system has been removed, esdeck now says to close ES-DE and start it
  again.

- **The window stayed responsive but the display did not.** Every line of
  output was posted to the window as it arrived, and Windows only delivers
  timer ticks to a message queue that has run dry - so on a busy sort the
  elapsed clock froze at one second and stayed there. Output is now collected
  and flushed a few times a second, with a bound on how much is drawn at once.
  Under a flood that used to leave the window minutes behind, the clock now
  ticks every second. A job that took five seconds takes one.

- Sizes throughout read in whatever unit suits them. A few hundred kilobytes
  of artwork used to report as `0 MB freed`.

- `build-exe.bat --no-pause` no longer waits for a keypress when the build
  fails - the one case where it could not report why it was stuck.

### Added
- **An activity strip on every job.** Along the bottom of the output: how long
  this has been running, and what the disk is actually doing - read and write
  throughput, sampled once a second from Windows' own I/O counters for the step
  that is running. Not scraped from the text above, so it keeps telling the
  truth through the long silences: hashing one 4 GB disc image, or waiting on
  7-Zip to work through a 47-part archive. When nothing is moving it says so,
  in as many words, rather than leaving you to guess.

  Above it, a progress bar that follows the real percentage when there is one
  to follow and sweeps when there is not.

- **Progress on the operations that had none.** Verifying the drop folder reads
  every byte on disk and is the slowest thing esdeck does; it now reports a
  bar, a rate and an estimate like everything else. Checking the library for
  artwork reports what it is walking through.

- **A heartbeat.** Steps that go quiet - one enormous file, an archive being
  listed - used to freeze the display, and a frozen display honestly reads as a
  hang. The status line now redraws on a timer of its own, with a spinner, so
  it always shows life whether or not anything has finished.

### Changed
- **Estimates follow the pace of the work.** They were extrapolating from the
  average speed since the job began, so a run that started on a hundred tiny
  ROMs and moved on to a 4 GB disc image gave a figure describing neither, and
  went on being wrong in the same direction for minutes. Time remaining is now
  bytes left divided by current throughput. In a case where the old estimate
  said twenty seconds, the new one says one, correctly.

## [0.15.0] - 2026-08-23

### Fixed
- **Updates could appear to do nothing when a copy of the source sat beside
  the .exe.** Python puts the working directory first on its import path, so a
  downloaded repo in the same folder as the application shadowed the installed
  package entirely. The version on screen was whatever was in that folder, and
  installing an update changed nothing you could see. The application now runs
  Python with the working directory kept off the import path, so it always uses
  the copy that updates actually replace.

- **The installed package reported version 0.11.0 no matter what it was.** The
  packaging metadata carried its own hand-written copy of the version, which
  stopped being bumped four releases ago. It is now read from the source, so
  there is one place to change it and no way for the two to drift apart.

## [0.14.0] - 2026-08-23

### Fixed
- **The Snorlax finally appears in the title bar.** The icon was there in the
  file and in Explorer, but every entry inside the .ico was stored as a PNG,
  and `System.Drawing.Icon` - the thing that puts an icon in a window's title
  bar and on the taskbar - cannot read PNG entries at all. It threw, the error
  was swallowed, and Windows drew its default icon instead.

  The small sizes are now written in the classic DIB form, which it does
  understand. 256px stays PNG, where the format requires it. If an .ico is ever
  unreadable again the application builds one from the artwork instead, so the
  icon cannot silently go missing.

- **"Games folder" shows the folder, not the drive.** It was reporting `D:\`
  where the library is actually `D:\ROMs`. That drive is the right answer to a
  setup question about where to put things, and the wrong answer to "where are
  my games".

### Changed
- **Updating asks before it installs.** Choosing *Check for updates* now looks
  first and prints what changed in every version you are behind, oldest first,
  and only then asks whether to install. It used to fetch the changelog and
  install in one go, which meant the summary scrolled past as a record of
  something already done rather than a thing to decide about.

## [0.13.0] - 2026-08-23

### Added
- **Freeing up space now ends with the figures that matter.** Every run closes
  with how many files were deleted, how much room that gave back, and how many
  were kept because they could not be verified against the library. A dry run
  says what it *would* delete and free, so the number you agree to is the number
  you get. Reading a wall of per-file lines and adding it up yourself was never
  a reasonable thing to ask.

  Empty folders removed are counted too, when there are any.

### Changed
- **The title bar carries the Snorlax icon.** `/win32icon` only stamps the icon
  on the file itself; the icon a window shows in its own title bar and in the
  taskbar is separate, and was still the default. The .ico is now compiled in
  and loaded at startup, so a moved or renamed .exe keeps it.

- Sizes in the space report read in whatever unit suits them - KB, MB, GB -
  rather than always being expressed in gigabytes, where anything small showed
  as `0.00 GB`.

## [0.12.0] - 2026-08-23

### Changed
- **Everything now runs inside the application.** Choosing an action no longer
  opens a console window; the output streams into a panel in the window itself,
  line by line, as the work happens. A **Stop** button ends the current run and
  **Back to menu** returns once it has finished.

  The reason is not just that it looks tidier. A console window is one careless
  click away from being closed in the middle of a sort, with no warning and no
  way to tell what had already been filed. The application asks.

- **The application asks before closing while a scan is running.** Closing the
  window mid-sort now prompts, naming the step in progress, and does nothing
  unless you confirm. Closing it while idle is unchanged.

- **Progress reports readable lines when its output is being captured.** The
  status line redraws itself with a carriage return, which a terminal renders
  as one updating line but a capturing reader renders as an unbroken smear.
  The bar, percentage, throughput and estimate are all still there - they are
  simply printed as a fresh line every few seconds instead.

### Added
- **The Snorlax icon and the poster background are compiled into the .exe.**
  Nothing sits beside the application and nothing is extracted at run time; the
  single file carries its own artwork. A picture placed in `assets/` still
  overrides it, so the background can be changed without a rebuild.

### Fixed
- The application failed to build against the .NET 2.0 libraries `csc.exe`
  references by default, which offer only the two-argument `Path.Combine`.

## [0.11.0] - 2026-08-23

### Added
- **ThuggyEmuAutomation.exe** - a real Windows application, not a batch file.
  Buttons for setting up, sorting, fixing the library, undoing, checking for
  problems, changing the icon and updating; each opens its own console so the
  progress bar and estimate stay visible. It shows the installed version and
  your games folder on screen.

  Built with `csc.exe`, the C# compiler that ships with Windows, so there is no
  toolchain to install, nothing bundled, and the result is 15 KB. `build-exe.bat`
  rebuilds it.

- The app icon is compiled into the .exe, so **`set-icon.bat` now rebuilds the
  .exe as well** - otherwise the shortcut would change and the application
  itself would keep the old icon.

### Note
- A batch file cannot be run from inside a ZIP - Windows offers to extract it
  first, which is what the "this application may depend on other compressed
  files" prompt means. Extract the download, then run the .exe.

## [0.10.1] - 2026-08-23

### Changed
- **Release pages now carry the full details themselves** rather than linking to
  the changelog and making the reader go and find it. `esdeck release-notes`
  prints a version's entry so a release is published with its own content:
  `gh release create vX --notes "$(esdeck release-notes X)"`. The v0.9.1 and
  v0.10.0 pages have been rewritten in place.

## [0.10.0] - 2026-08-23

### Added
- **The Desktop icon works out of the box.** A placeholder icon ships with the
  project and setup builds the shortcut from it, so the launcher has a real icon
  rather than the default batch-file one. Batch files cannot carry an icon
  themselves - a shortcut can, which is why setup creates one.
- **`set-icon.bat`** - drag any square PNG onto it to use your own artwork. It
  crops to the circle, makes the corners transparent, rebuilds the `.ico` and
  the shortcut. Note that Windows caches shortcut icons: press F5 on the Desktop
  if the old one lingers.

## [0.9.1] - 2026-08-22

### Added
- **The changelog is shown before you are asked to update.** Every version you
  missed is listed in order, oldest first, with what changed in each - so being
  several updates behind explains itself instead of arriving as one opaque
  jump. Only then does it ask "Update now?".

## [0.9.0] - 2026-08-22

### Added
- **ThuggyEmuAutomation** - the launcher is now named, and takes an icon.
  `esdeck icon` crops a square picture to the circle inside it, makes the
  corners transparent so a black background disappears, writes a multi-size
  Windows `.ico`, and creates the Desktop shortcut. Batch files cannot carry an
  icon themselves; a shortcut can. Done with the standard library alone - a PNG
  is zlib-compressed scanlines, and an .ico may hold PNG payloads directly.

### Fixed
- **The update check could report a stale version.** It read
  raw.githubusercontent, which is CDN-cached for several minutes, so straight
  after a push it still answered with the old version - observed live. It now
  asks the GitHub API, which returns the current file, and falls back to the raw
  URL only if the API cannot be reached.

## [0.8.0] - 2026-08-22

### Added
- **`esdeck-launcher.bat` - the only file you need to keep.** It checks GitHub
  on every launch, updates itself, the other .bat files and the package when
  anything is newer, then offers a menu: set up, sort, fix, undo, doctor, free
  space. No more re-downloading a ZIP to get a fix.

  This closes a real trap: the .bat files are only launchers, so copying a
  fresh one out of a download does not update the code it runs. The launcher
  updates the package too, which is the part that matters.

- **`esdeck update`** checks and installs on its own, and only fetches the full
  download when the version actually differs - the check is a single small file.
  Versions compare numerically, so 0.10.0 correctly beats 0.9.0.
- **`fix-library.bat`** - repairs a library sorted by an older version, in one
  pass. Removes artwork filed as games, makes the controller player 1, then
  offers to free the Incoming copies.
- **`esdeck cleanup`** removes artwork that an older esdeck filed as games. It
  checks **every** system folder, not just pico8 and tic80 - box art turned up
  under n64 and snes as well. Genuine PICO-8 cartridges really are `.png`, so
  those are identified by their 160x205 dimensions and kept.
- **`esdeck controller`** fixes the pad being treated as player 2: it pins
  RetroArch's player 1 to the first pad and selects the XInput driver, which
  enumerates Xbox pads first. It also reports every device competing for the
  slot, since a virtual device from Razer or Corsair software is a common cause.
  The keyboard is deliberately left working - it is not a "player" in RetroArch
  and disabling it only removes a fallback.

## [0.7.1] - 2026-08-22

### Fixed
- **The scan phase showed nothing at all.** Progress covered the copying, but
  reading a large drop folder is the slower half - every archive is opened to
  list its contents and every disc image is read for its signature - so a sort
  of a big collection sat on "[1/4] Reading the drop folder" for a long time
  with no sign of life. It now reports a running count and the item it is
  looking at, and finishes with how long the scan took.
- Where the size of a job is not known in advance, a counter is shown instead
  of a progress bar frozen at 0%, which reads as no progress at all.

## [0.7.0] - 2026-08-22

### Added
- **Undo.** Every sort records exactly which files and folders it created, so
  `esdeck undo` reverses it - or `sort-games.bat --undo`. A sort you cannot
  reverse is a sort you are afraid to run, which matters most on the first
  attempt with a messy collection.

  Undo removes only what that run created, and only where the file is still
  exactly as it was left - same size, same modification time. Anything touched
  since is kept and reported, because by then it is not esdeck's to remove. A
  folder that still holds something is left alone. Your originals in the drop
  folder are never involved: esdeck copies, so they were never moved.

- **`esdeck history`** lists previous sorts with their date, file count and
  size, and `esdeck undo --run ID` reverses a specific one rather than the last.

## [0.6.0] - 2026-08-22

### Added
- **Progress, throughput and a time estimate.** Filing a few thousand games
  moves tens of gigabytes; without feedback that is indistinguishable from a
  hung program. The estimate is based on bytes rather than file count, because
  game files run from 32 KB to 4 GB.

      [########--------------------]  28.4%  912/3260  4.1 GB/14.6 GB
      38.2 MB/s  elapsed 1m 48s  left 4m 34s  Sonic the Hedgehog (USA).md

- **One copy of each game.** A dump folder holds the same title several times
  over - `[!]`, `[h1]`, `[f1]`, regional variants. esdeck keeps the best copy
  and reports the rest, ranking by the GoodTools tags: a verified `[!]` dump
  beats a hack, which beats a bad dump. Nothing is deleted; duplicates are
  simply not filed. `--keep-duplicates` files them all.

### Fixed
- **Artwork was being filed as games.** ES-DE lists `.png` as a valid extension
  for pico8 and tic80, so every screenshot in a collection became its own
  library entry - one folder produced a game called "screenshot". Images,
  video, audio and manuals are now media, never games; a folder holding only
  artwork is skipped; and the count shown says how many images were ignored.

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
