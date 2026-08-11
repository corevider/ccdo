# Changelog

Notable changes to ccdo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

Sections are generated from the commit log by `tools/changelog.py`, so a
release's notes on GitHub and its entry here say the same thing.

<!-- releases -->

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
