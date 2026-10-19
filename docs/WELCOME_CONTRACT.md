# Welcome window contract

Locked 2026-10-19 (Vaihe 8). The implementation and its tests are written against
this file; changing behaviour described here needs the project owner's approval.

## Purpose

A small window that greets a new user at their first login and shows the few
things that are not discoverable by looking at the desktop: switching between light
and dark mode, the search and overview shortcuts, and where the settings are. It is
a guide, not a configuration tool: every action it offers is also available in the
regular settings.

## Package

- Directory `packages/kuura-welcome/`, package name `${DISTRO_NAME}-welcome`
  (built from the same DISTRO_NAME variable as every other package here),
  `arch=('any')`, license GPL-3.0-or-later.
- Pulled in by the metapackage `packages/kuura-desktop`.
- No compiled code. The window is plain QML run by the QML runtime that the Qt 6
  declarative package already ships (verify the exact runner binary name and path
  against the pinned package, docs/VERSIONS.md). A small POSIX `sh` launcher
  `/usr/bin/${DISTRO_NAME}-welcome` chooses the mode and starts the runner.
- New runtime dependencies must already be in the pinned snapshot and must pass the
  licence rules in CLAUDE.md; prefer none beyond what Plasma already pulls in.

## Look

- Every colour, radius, spacing, font size, font family and duration comes from the
  generated token singleton (`design/generators/qml_singleton.py`, both modes). No
  literal values in QML except layout structure (anchors, counts). Follow how the
  other QML consumers in this repository get generated files into their package.
- The window opens in the mode that is active at launch (light or dark). How the
  current mode is detected must match how the product itself switches modes; find
  that mechanism in the product (colour scheme selection) and document it in the
  launcher.
- Fixed window size, centred, regular decorated window (title bar from the window
  manager), non-resizable. Title: "Welcome to ${DISTRO_NAME}" with the distribution
  name capitalised as everywhere else in the UI.
- English UI text, like the rest of the user interface. No name from
  distro-tyonkulku.md section 1.2 anywhere (the forbidden-terms check runs on the
  package).

## Content (top to bottom)

1. Heading and one sentence of welcome.
2. **Appearance**: two choices, Light and Dark, showing the current one as
   selected. Choosing one applies the product's own light or dark colour scheme
   immediately, with the same command the product uses for the switch, and the
   window itself follows.
3. **Shortcuts**: search and overview, each with its key combination. The
   combinations are read from the product's shipped configuration
   (`packages/kuura-shell/skel/.config/kglobalshortcutsrc`, `krunnerrc`, or the
   upstream defaults they rely on) at package build time or at run time, never
   typed into the QML by hand, so they cannot drift.
4. **Settings**: a button that opens System Settings.
5. Bottom row: a checkbox "Show this window at login" (checked by default) and a
   Close button (default button, Escape also closes).

## Autostart

- `/etc/xdg/autostart/${DISTRO_NAME}-welcome.desktop` runs the launcher with
  `--autostart`.
- With `--autostart`, the launcher exits 0 without opening anything when
  `~/.config/${DISTRO_NAME}-welcomerc` has `[General] ShowAtLogin=false`.
  Missing file or key means show.
- Unchecking the checkbox writes `ShowAtLogin=false` (and checking it writes
  `true`) through KConfig-compatible tooling (`kwriteconfig6`), as the user.
- A desktop entry in the application menu starts the window without
  `--autostart`, so it always opens, whatever the setting.
- The product does not ship `~/.config/${DISTRO_NAME}-welcomerc` in /etc/skel.

## Test harness

- Every existing state must stay unchanged: the window must not appear in any of
  them. The screenshot image and install-verify both get a TEST-ONLY
  `~/.config/${DISTRO_NAME}-welcomerc` with `ShowAtLogin=false` via
  `harness/vm/guest/skel/` (the product does not ship that file, so this is the
  right place; install-verify copies that directory already).
- New state `welcome-window` in `harness/states.toml`, both modes, started with
  the launcher WITHOUT `--autostart`. A test-only window rule fixes its position
  like the other windows (`harness/vm/guest/skel/.config/kwinrulesrc`).
- Its goldens are added only by the project owner (goldens-accept).

## Tests

- Launcher: `--autostart` with the setting false, true, missing file, missing key,
  malformed file (treated as show); mode detection for light, dark and unknown
  (falls back to light).
- Package: the files land at the paths above; the autostart entry passes
  `--autostart`; the menu entry does not; no forbidden terms.
- QML: lint with the pinned Qt's linter if it is available in the build image;
  a test that the QML contains no literal colours or pixel sizes outside the token
  singleton.
