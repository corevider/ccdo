# Changelog

Notable changes to ccdo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

Sections are generated from the commit log by `tools/changelog.py`, so a
release's notes on GitHub and its entry here say the same thing.

<!-- releases -->

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
