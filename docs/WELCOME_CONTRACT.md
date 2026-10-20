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
- With `--autostart`, the launcher also exits 0 without opening anything when the
  system was booted from the live medium (decided 2026-10-20 by the project owner:
  in the live session the user is there to try or install the system, the window
  belongs to the installed system's first login, and in the live session it pushed
  the installer window aside). Detection uses a marker that exists only on a live
  boot of this medium; the installed system must never match it. The menu entry
  still opens the window in the live session.
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

## Implementation notes

No behaviour above was changed. Details the implementation had to settle:

- Runner: `/usr/bin/qml6` (a symlink to `/usr/lib/qt6/bin/qml`) from the pinned
  `qt6-declarative` (checked in the screenshot image, 6.11.2). The package depends on
  `qt6-declarative`, `qt6-wayland`, `kconfig`, `plasma-workspace` and `systemsettings`,
  all already in the snapshot.
- QML cannot start programs or write files. The window reports each action as one
  line `WELCOME_ACTION <verb> [argument]` on its log output (the launcher sets
  `QT_FORCE_STDERR_LOGGING=1` and a plain message pattern); the launcher performs only
  the exact verbs `scheme light|dark`, `show-at-login true|false` and `settings`.
  Facts for the window (mode, title, key combinations, current setting) are passed as
  `--name=value` arguments after `--`.
- Mode detection: `[General] ColorScheme` of `kdeglobals` (user file, then
  `/etc/xdg/kdeglobals`) equal to `<name>-dark` means dark; anything else is light.
  This is what `plasma-apply-colorscheme <name>-light|dark` records.
- Shortcuts at run time, first hit wins: the user's `kglobalshortcutsrc`, the one the
  product ships in `/etc/skel`, then the upstream default. Search: KRunner's
  `X-KDE-Shortcuts` in its desktop file. Overview: KWin compiles its default in, so it
  is recorded in `shortcut-defaults.conf` of the package (a test keeps it equal to the
  key the harness state `overview` presses).
- Harness: the state `welcome-window` runs `sh -c "exec /usr/bin/*-welcome"`; the
  reset step of `harness/states.toml` also stops the window (pattern `[-]welcome`).
  The window rule matches the title substring "Welcome to", because the QML runtime
  announces its own application id.
- Application id (shelf entry and icon): Qt 6.11.2 Wayland announces
  `<reversed organisation domain>.<executable name>` as the id, here `qml`, and the QML
  can set `Qt.application.domain` (the name and organisation have no effect). The
  launcher passes `--app-domain=<name>-welcome`; the QML applies it before it shows the
  window (it starts hidden), so the id is `<name>-welcome.qml` (verified with
  `WAYLAND_DEBUG` against kwin in the screenshot image). The menu entry names that id
  in `StartupWMClass`, so Plasma pairs the window with the entry and its icon. The
  project's icon theme has no fitting welcome glyph, so the entry keeps the standard
  `help-about`. Qt offers no QML property for a window icon. The title-based window
  rule stays as it was.

- Live-medium detection: the launcher treats the directory `/run/archiso` as the
  marker of a live boot. archiso's initramfs hook (`mkinitcpio-archiso`, `hooks/archiso`)
  creates and mounts `/run/archiso/bootmnt`, `airootfs`, `cowspace` and `copytoram`;
  `/run` is a tmpfs emptied every boot and the installed system's initramfs has no
  archiso hooks, so the directory cannot exist there. The check runs before the
  `ShowAtLogin` read and only with `--autostart`; tests place the marker under
  `WELCOME_ROOT`.
