# Changelog

Notable changes to ccdo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

Sections are generated from the commit log by `tools/changelog.py`, so a
release's notes on GitHub and its entry here say the same thing.

<!-- releases -->

## [1.0.53] - 2026-09-03

### Fixed

- **gui:** give the terminal a moment to show the session's name in its title (677dc9d)
## [1.0.52] - 2026-08-30

### Added

- **cli:** install-window-calls asks GNOME Shell for the extension (c3061d5)
## [1.0.51] - 2026-08-30

### Fixed

- **gui:** switching the last-used terminal tab to a session is opt-in (8cfcd89)
## [1.0.50] - 2026-08-30

### Added

- **gui:** show the session's own terminal on Wayland where it can be done (5c68dce)
## [1.0.49] - 2026-08-30

### Fixed

- **gui:** no terminal button on the ideabox (184f0cd)
## [1.0.48] - 2026-08-30

### Added

- **gui:** a button that shows the session's terminal (5a6b070)
## [1.0.47] - 2026-08-30

### Fixed

- **gui:** the shortcut hint shows each key as a badge beside its action (5aa7f69)
## [1.0.46] - 2026-08-30

### Fixed

- **gui:** rename and color work on a busy session; the ⋮ menu is the session's own (269bb4c)
## [1.0.45] - 2026-08-30

### Fixed

- **gui:** a directory or name that arrives later reaches the page (a2586ad)
## [1.0.44] - 2026-08-30

### Added

- **gui:** rename and color a session through Claude Code; every tab shows its path (c85fdc6)
## [1.0.43] - 2026-08-30

### Added

- **settings:** switches for the status line's chips and ccdo's own line (db20bb8)
## [1.0.42] - 2026-08-30

### Added

- **gui:** the status chips name the git branch (0de0a9e)
## [1.0.41] - 2026-08-30

### Added

- **gui:** show the status line's facts under a session's title (32bcb31)
## [1.0.40] - 2026-08-30

### Fixed

- **hooks:** a handed-over note finishes when its turn ends; working means that note (ed71099)
## [1.0.39] - 2026-08-30

### Fixed

- **gui:** the cross on a closed tab closes it; the tray menu matches the window (3180edb)
## [1.0.38] - 2026-08-30

### Added

- **gui:** the ideabox hands notes out instead of running them; ⇄ asks first (69c919a)
## [1.0.37] - 2026-08-30

### Added

- **macos:** close a closed session's entry; send notes back to the ideabox (6e1a891)
## [1.0.36] - 2026-08-30

### Added

- **gui:** close an ended session's tab; send notes back to the ideabox (5f158ce)
## [1.0.35] - 2026-08-30

### Added

- **gui:** sent rows say when the note went out; the README shows the ideabox (d917967)
## [1.0.34] - 2026-08-30

### Added

- **gui:** the ideabox page explains itself (04dfbe3)
## [1.0.33] - 2026-08-30

### Fixed

- **gui:** choosing the ideabox no longer scrolls the tab strip (ce9c620)
## [1.0.32] - 2026-08-29

### Added

- **macos:** hourly update check and a notification for a new release (e8fad10)
## [1.0.31] - 2026-08-29

### Added

- **tray:** hourly update check reaches the network and announces a release (1918b62)
## [1.0.30] - 2026-08-29

### Added

- **gui:** color bar shows each task's stage (d58f24d)
- **gui:** pin the ideabox tab left of the strip (0145bc1)
## [1.0.29] - 2026-08-14

### Fixed

- **macos:** wait for a screenshot that is still in the thumbnail (bbc98fd)
## [1.0.28] - 2026-08-14

### Fixed

- **macos:** ask macOS for the temporary folder instead of trusting TMPDIR (9feeeca)
## [1.0.27] - 2026-08-14

### Fixed

- **macos:** find the screenshot while the thumbnail still has it (150801b)
## [1.0.26] - 2026-08-13

### Added

- **cli:** paste-check reports the screenshot side too (a1e7511)
## [1.0.25] - 2026-08-13

### Fixed

- **macos:** paste the newest screenshot, not whatever the clipboard still holds (514c0d6)
## [1.0.24] - 2026-08-13

### Added

- **notes:** drop files on the Linux note box, and paste a screenshot taken to file (1bd1637)
## [1.0.23] - 2026-08-13

### Added

- **macos:** drop files on the note window, and quote every path (85ed125)
## [1.0.22] - 2026-08-13

### Fixed

- **macos:** answer Command+V in the note window (4bf177c)
## [1.0.21] - 2026-08-13

### Performance

- **macos:** keep the pasteboard's PNG bytes instead of re-encoding them (20a3f91)
## [1.0.20] - 2026-08-13

### Fixed

- **cli:** paste-check no longer trusts a deprecated API alone (2178529)
## [1.0.19] - 2026-08-12

### Added

- **tmux:** keep the terminal's own scrolling and selection by default (81db83f)
## [1.0.18] - 2026-08-12

### Fixed

- **tmux:** keep a mouse selection going to the system clipboard (896b85c)
## [1.0.17] - 2026-08-12

### Added

- **cli:** ccdo paste-check, for when a paste does nothing (25cc27e)

### Fixed

- **macos:** read pasted images through NSImage, not two named types (ffd09bb)
## [1.0.16] - 2026-08-12

### Added

- **macos:** a note window with many lines and pasted images (4848b9e)
## [1.0.15] - 2026-08-12

### Fixed

- **install:** pick a macOS interpreter that carries PyObjC (825ffd5)
- **macos:** make the menu bar app start and survive Cocoa (e5b4ac4)
## [1.0.14] - 2026-08-12

### Added

- **macos:** a native menu bar app instead of the GTK window (cb74355)
## [1.0.13] - 2026-08-12

### Fixed

- **tmux:** make the wheel scroll in the session claude-tmux opens (69a0e23)
## [1.0.12] - 2026-08-12

### Fixed

- **macos:** open dialogs after the menu closes, not from inside it (4a135fe)
## [1.0.11] - 2026-08-12

### Fixed

- **macos:** name the app ccdo, and stop it floating over the menu bar (d5880e1)
- **macos:** install librsvg, and stop the window drawing a pale frame (bf6269d)
## [1.0.10] - 2026-08-12

### Added

- **install:** set up the Claude Code hooks during install (67aada5)
## [1.0.9] - 2026-08-12

### Fixed

- **install:** install the latest release, not main (3c3d168)
## [1.0.8] - 2026-08-12

### Fixed

- **update:** install the release that was announced, not main (167be2b)
## [1.0.7] - 2026-08-12

### Added

- **macos:** support macOS properly — GTK, the menu bar and launchd (51b1b69)
## [1.0.6] - 2026-08-12

### Fixed

- **macos:** draw the tray icon so it does not need an SVG loader (a2089d6)
- **i18n:** translate the CLI output and the strings the sweep missed (56dfc03)
- **install:** install for an interpreter that can import gi (3b01af2)
## [1.0.5] - 2026-08-12

### Added

- **platform:** work on more distros and on macOS (b1afb61)
## [1.0.4] - 2026-08-12

### Fixed

- **ui:** keep the version line in sight in the settings window (a736107)
## [1.0.3] - 2026-08-12

### Added

- **cli:** print the release notes in the terminal too (36bae39)
## [1.0.2] - 2026-08-12

### Added

- **ui:** show the release notes in the window and update from there (c287024)

### Fixed

- **install:** only reach for apt when a dependency is missing (acb22d8)
## [1.0.1] - 2026-08-12

### Added

- **cli:** let ccdo update run the installer (cb3fb57)
- **ui:** give dialogs the desktop's own title bar (1238fab)
- **theme:** use Claude's terracotta as the neutral accent (e250289)
- **ui:** move Settings above Quit in the tray menu (806891f)

### Fixed

- **i18n:** translate the settings window title (c37cb33)
## [1.0.0] - 2026-08-11

First release.

### Added

- A tab per live Claude Code session; a note goes to the session whose tab you
  wrote it under.
- Delivery over tmux as a bracketed paste, so multi-line text arrives whole and
  never submits halfway through. Outside tmux, the Stop hook hands the task
  over when the turn ends.
- Auto-advance with a spend budget, held back when Claude ends a turn with a
  question — a task never stands in for the user's answer.
- A decision log answering "why didn't this go?", surfaced in the window as
  well as through `ccdo log`.
- Screenshots pasted into a note are saved to disk and referenced by path, so
  the queue stays plain text.
- One design token set, with light and dark palettes that follow the desktop.
- English source strings with JSON translation catalogs; Türkçe included.
