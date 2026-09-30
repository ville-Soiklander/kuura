# Desktop shell contract (V3)

Locked interface of the desktop shell (working brief, Vaihe 3): the panel layout, window
decoration, keyboard shortcuts, search theme and application theming that turn a plain
Plasma session into the project's own look. Follows the same pattern as
`docs/BUILD_CONTRACT.md` and `docs/HARNESS_CONTRACT.md`: change this document
deliberately and keep every implementation in step with it.

## Scope (from the working brief, Vaihe 3)

Styles and configures **stock KDE/GTK components** more deeply than the placeholder
configuration the V2 test image uses; it does not build the bespoke Beacon/Shelf/Overview
surfaces themselves (that is later work). Delivers:

1. Panel layout: a 26px top panel (Global Menu widget left, systray + clock right) and a
   floating bottom panel (Icons-only Task Manager, icon magnification on hover).
2. KWin: window buttons on the left; corner radius and shadow driven by `design/tokens.json`.
3. Keyboard shortcuts: search, window overview, close/hide window, switch workspace.
4. KRunner: centred floating panel, material driven by tokens.
5. Overview effect: spacing and animation curves driven by tokens.
6. Kvantum (Qt) and GTK4/libadwaita theming installed and set as the system default.

**DoD** (verified with the V2 harness, `docs/HARNESS_CONTRACT.md`): `desktop-empty`,
`menubar-open`, `shelf-hover` (renamed from the working brief's own original term for
this element, which named a different desktop environment's launcher tray), `overview`,
`search-open` pass the pixel comparison against new, human-approved goldens. The global
menu shows real menus for both a Qt application (Dolphin) and a GTK application.

## Package: `packages/kuura-shell/`

A new package, installed by `kuura-desktop` (added to its `depends`). Ships no upstream
source; like `kuura-desktop` it is built from this monorepo. License GPL-3.0-or-later
(`docs/LICENSES/README.md`: "themes, configuration, scripts").

- `PKGBUILD`: `build()` runs `python3 -m design.generate` against this repository's own
  `design/` tree (copied into the build container next to `packages/`, see
  `build/Containerfile`) to produce the light/dark colour scheme, Kvantum and GTK4 files
  at package-build time — never generated at first login, so the result is reproducible
  from the pinned archive snapshot like everything else the project ships.
- `skel/`: default configuration for new users, installed to `/etc/skel/.config/...`
  (`install -Dm644`, same idea as `harness/vm/guest/skel/` but for the real product, not
  test-only overrides): the panel layout, `kwinrc` (button placement, shortcuts-relevant
  keys), `kglobalshortcutsrc`, KRunner theme selection, colour scheme selection, Kvantum
  and GTK4 theme selection.
- Generated theme files install to the standard system locations (not `/etc/skel`, they
  are shared): `/usr/share/color-schemes/`, `/usr/share/Kvantum/<name>/`,
  `/usr/share/themes/<name>/gtk-4.0/`.

**Two things below are OPEN, not assumed** — verify them empirically in the guest image
before writing the package(), rather than guessing a plausible-sounding mechanism:

- How Kvantum and GTK4/libadwaita each actually switch between a light and a dark variant
  system-wide (two separate Kvantum theme directories plus something that toggles the
  active one? GTK4's `gtk-dark.css` convention? something else?). Report what you find
  and why, then implement it.
- How KWin 6.7.5 actually offers a corner-radius/shadow lever for window decorations
  (a config key of the stock decoration, an Aurorae SVG theme, something else). If the
  real mechanism needs materially more work than a config file (for example, a bespoke
  Aurorae theme with SVG assets), STOP and report the finding as a scope question rather
  than building it silently — this mirrors the working brief's own escalation rule.

## Known issue: KWin decoration does not render Breeze KDecoration3 chrome

**Open, unresolved, budget-stopped — do not silently retry past this.** In the V2 test
image, windows render a generic titlebar (icon, title, a chevron, a single close button)
instead of Breeze's real KDecoration3 chrome (four distinct buttons: menu, minimize,
maximize, close). This is visible even in the already-approved V2 goldens
(`harness/goldens/{light,dark}/files-window.png` etc.) — it predates V3 and was only
noticed while investigating V3's window-button-placement requirement above.

Three separate investigation threads (two subagents, ~30–45 min each, plus roughly a
dozen of the orchestrator's own direct boot cycles via `harness/spike/boot_capture.sh`)
ruled out, with concrete evidence each time:

- Wrong config group or file: the KCFG schema
  (`/usr/share/config.kcfg/kwindecorationsettings.kcfg`) confirms the group is still
  `org.kde.kdecoration2` (unchanged name despite the KDecoration3 API) with
  `library=org.kde.breeze` and `buttonsOnRight=HIAX` as the **defaults** — meaning
  4-button Breeze chrome should already be the out-of-the-box result with zero config.
- Wrong user/file target: `kwriteconfig6` via `desktop-run` verifiably persists to
  `/home/desktop/.config/kwinrc`, and `qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure`
  returns success — but a screenshot taken immediately after shows no visual change at
  all.
- Missing shared library: `ldd` on `org.kde.breeze.so` (KDecoration3 plugin path)
  resolves every dependency.
- Wayland server-side-decoration negotiation not happening: refuted with a
  `WAYLAND_DEBUG` trace showing the `zxdg_decoration_manager_v1` exchange completing
  normally.
- Silent logging swallowing a real plugin-load failure: attempted to force
  `QT_LOGGING_RULES` on for `kwin_core`/`kwin_platform`/`kdecorations` via a
  `~/.config/plasma-workspace/env/*.sh` script (the documented mechanism for injecting
  env vars before KWin starts). The variable still does not reach the `kwin_wayland`
  process's environment on a fresh boot, and `journalctl -b` shows **zero** lines
  mentioning kwin/decoration/breeze for the entire boot — indicating the gap is in this
  image's systemd user-session startup sequencing (`plasma-workspace-wayland.target` and
  how/whether it sources `plasma-workspace/env/`), not just a quiet log level. This is a
  materially deeper rabbit hole than the bounded investigation that was authorized, so it
  was stopped here rather than pursued further without checking back in.

**Net effect on V3 scope:** the `skel/.config/kwinrc` button-placement/shortcut keys
above are written correctly and DO persist, but cannot be verified to visibly change
anything until this rendering gap is understood — button placement is moot if the
decoration itself isn't the real Breeze one. Treat any new goldens captured before this
is resolved as capturing the *generic* titlebar, not the project's intended chrome, and
say so explicitly in the review rather than approving it as if it were correct.

## Dark mode: Kvantum and GTK4/libadwaita (verified)

The two open questions from the "Package: `packages/kuura-shell/`" section above were
investigated live in the guest image (KWin 6.7.5-1, kvantum 1.1.8-1, xdg-desktop-portal
1.22.1-2, xdg-desktop-portal-kde 6.7.5-1) rather than assumed. They turned out to have
two different answers, verified with different confidence, and are implemented in
`packages/kuura-shell/PKGBUILD`.

**Kvantum has no light/dark concept inside one theme — confirmed by inspecting the
theme directories the package itself ships.** `ls /usr/share/Kvantum` on the guest
image lists pairs like `KvArc`/`KvArcDark`, `KvMojave`/`KvMojaveLight`,
`KvSimplicityDark`/`KvSimplicityDarkLight` — always as fully separate directories,
never one directory with a variant switch. Each directory contains a single, same-named
`.kvconfig` (e.g. `KvArc/KvArc.kvconfig`) plus its SVG assets. The active theme is
chosen by a completely separate, tiny global file: `kvantummanager --set KvArcDark`,
run live, wrote exactly this to `~/.config/Kvantum/kvantum.kvconfig`:
```
[General]
theme=KvArcDark
```
— confirming editing that file directly (no GUI, no `kvantummanager` needed at deploy
time) is equivalent. A second, easy-to-miss finding: Kvantum is *installed* by
`kuura-desktop`'s dependencies but not *active* out of the box — a fresh account's
`kdeglobals` has no `widgetStyle` key at all, and Qt6/KDE falls back to
`widgetStyle=Breeze`. Setting `widgetStyle=kvantum` (`kwriteconfig6 --file kdeglobals
--group KDE --key widgetStyle kvantum`) followed by a **fresh** `dolphin` launch (no
logout/login needed) visibly switched Dolphin to the active Kvantum theme's own flat,
dark widget look — screenshotted before/after. So the mechanism needs three things
together, all implemented as `packages/kuura-shell/skel/` files: `kdeglobals`
(`widgetStyle=kvantum`, makes Kvantum the style at all), `Kvantum/kvantum.kvconfig.in`
(`theme=<name>-light`, picks which installed theme), and two theme directories per
`package()`, `/usr/share/Kvantum/<name>-light/` and `/usr/share/Kvantum/<name>-dark/`,
each containing a same-named `.kvconfig` built by `design/generators/kvantum.py`.

**GTK4/libadwaita: two different mechanisms exist on this image, verified to different
degrees.** `busctl --user call org.freedesktop.portal.Desktop
/org/freedesktop/portal/desktop org.freedesktop.portal.Settings ReadAll as 1
org.freedesktop.appearance`, run before and after `plasma-apply-colorscheme
BreezeDark`/`BreezeLight`, showed `color-scheme` change live and correctly: `2`
("prefer light") while `BreezeLight` was active, `1` ("prefer dark") right after
switching to `BreezeDark`, `2` again after switching back — with **no extra plumbing**,
because `xdg-desktop-portal-kde` is already a `kuura-desktop` dependency and this
already runs on every mode switch the harness performs (`plasma-apply-colorscheme`,
`harness/shots/runner.py`'s `apply_mode`). This is the mechanism `libadwaita`'s
`AdwStyleManager` is documented to read, and it needs nothing new installed by
`kuura-shell` to work — it already works today.

The second, older mechanism — one GTK4 theme directory holding both
`gtk-4.0/gtk.css` (light) and `gtk-4.0/gtk-dark.css` (loaded instead of it when
`GtkSettings:gtk-application-prefer-dark-theme` is true) — is the standard, documented
GTK convention (not invented here) and is why this document already named a single
`/usr/share/themes/<name>/gtk-4.0/` path rather than two. **It could not be confirmed
visually working in this image, and that is reported rather than papered over:** GTK4
and libadwaita are not part of the metapackage's dependency graph (nothing this
repository installs pulls them in), and the guest has no network (`-nic none`,
`harness/spike/vm_capture.py`) to add a GTK4 test app for the investigation. A live A/B
test was still possible with GTK3 (present via `firefox`, the test image's browser): a
throwaway theme (`/usr/share/themes/testkuura/gtk-3.0/{gtk.css,gtk-dark.css}`, solid red
vs. solid blue `window` background — an impossible-to-miss difference) was installed and
selected through exactly this mechanism (`~/.config/gtk-3.0/settings.ini`:
`gtk-theme-name=testkuura`, `gtk-application-prefer-dark-theme=1`), then Firefox was
launched fresh. Result: **no visible change at all**, screenshotted, even though the
portal mechanism above demonstrably does change live in the same image. The most likely
explanation is that Firefox's own chrome does not render through the system GTK theme's
CSS at all (a known Firefox/GTK quirk — Firefox has its own theming layer and is
plausibly following the portal instead, consistent with the result) rather than the
`gtk.css`/`gtk-dark.css` swap being broken for an ordinary GTK app — but the tools
available in this image could not tell the two apart. `packages/kuura-shell/PKGBUILD`
still ships `gtk-4.0/{gtk.css,gtk-dark.css}` (generated by `design/generators/gtk_css.py`)
and a templated `skel/.config/gtk-4.0/settings.ini.in`, because this is exactly what this
document's `package()` bullet already named and it is a plain config file, not the kind
of bespoke work the working brief's escalation rule would stop this change on — but
unlike the Kvantum and portal mechanisms above, **its visual effect is unverified**, and
the skel file's own comment carries this same caveat forward for whoever revisits it.

## Panel layout generator: `design/generators/plasma_layout.py`

A fifth generator alongside the four from V1 (`plasma_colors.py`, `kvantum.py`,
`gtk_css.py`, `qml_singleton.py`), wired into `design/generate.py` the same way. Reads
only `tokens["panel"]` and `tokens["radius"]["panel"]`.

**Revised 2026-09-29 — the scripting-API version of this contract is abandoned.** A
build against it produced a correct `evaluateScript` JS script that
`packages/kuura-shell` never actually ran against anything: the package only ever
installed static `/etc/skel/...` files, with no first-login trigger of any kind, so the
generated panel layout never reached a booted session (found live: `desktop-empty` on a
freshly built guest image still showed the old, untouched stock panel; the running
session's own `~/.config/plasma-org.kde.plasma.desktop-appletsrc` was byte-for-byte the
V2 harness's stock skel file). Rather than design and verify a new runtime trigger
mechanism (autostart entry or systemd-user one-shot unit calling `evaluateScript` once
at first login, with a marker file so later logins do not clobber user changes), this
generator now produces a COMPLETE, ready-to-install
`plasma-org.kde.plasma.desktop-appletsrc` INI file directly — matching the mechanism
`kwinrc`/`kglobalshortcutsrc`/`kdeglobals` already use successfully, and standard
practice for how Plasma-based distributions ship a customised default panel. Output
format: verify the real ini keys live in the guest image (do not guess a
plausible-sounding key name) — `harness/vm/guest/skel/.config/
plasma-org.kde.plasma.desktop-appletsrc` is a real, working reference for the format's
general structure (Containments, Applets sub-sections, AppletOrder), and applying the
old scripting-API generator's script once by hand through `evaluateScript` in a live
guest, then reading back the appletsrc it produced, is a fast way to get the exact keys
for panel thickness and for a floating, centred panel without guessing — its widget ids
and panel semantics were never shown to be wrong, only never actually applied.

Exact content (values from tokens, everything else literal): one top panel, height
`tokens.panel.menubar_height`, containing (left to right) the application menu button,
then a Global Menu widget, then a spacer, then a system tray widget, then a digital clock
widget. One bottom panel, floating, containing a centred Icons-only Task Manager widget
whose icon size is `tokens.panel.shelf_icon` and hover zoom factor is
`tokens.panel.shelf_hover_scale`; the panel's own margin from the screen edge is
`tokens.panel.shelf_margin`. Corner rounding of both panels (if the ini surface
supports it directly; otherwise leave to the `skel/` KWin/Plasma-theme configuration
and say so in the report) uses `tokens.radius.panel`. Everything else a valid appletsrc
needs (desktop containment, wallpaper, `[ActionPlugins]`, activity id) is this
generator's own responsibility too, using Plasma's real defaults confirmed live — not
the V2 test harness's own test-only simplifications (fixed solid-colour wallpaper,
curated launcher favourites), which do not apply to the real shipped product.

```python
def render(tokens: dict) -> str:
    """
    Render a complete, ready-to-install plasma-org.kde.plasma.desktop-appletsrc file
    (mode-independent: layout has no light/dark variant).

    Args:
        tokens: Validated token dictionary (see design/validate.py).

    Returns:
        The complete appletsrc content, exactly as specified above.
    """
```

`design/generate.py` writes this to `<out-dir>/layout/plasma-org.kde.plasma.desktop-appletsrc`
(one file, no mode suffix, named after its real install target rather than
`<name>-layout.js` as before — the filename is Plasma's own, not the distro theme's, so
`packages/kuura-shell/PKGBUILD`'s `package()` installs it verbatim: `install -Dm644
"$generated/layout/plasma-org.kde.plasma.desktop-appletsrc"
"$pkgdir/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc"` — this install line
was missing before and is the actual bug that started this revision; adding it is
required, not optional, for this whole section to have any effect). Update the locked
`generate()` docstring's file count from 8 to 9 and its manifest accordingly if not
already done.

## Keyboard shortcuts (`skel/.config/kglobalshortcutsrc`)

Bound to the **stock** components that stand in for the future bespoke ones (matches the
harness states, `docs/HARNESS_CONTRACT.md`): search → the stock KRunner's own default
shortcut component; overview → the stock Overview effect's own default shortcut
component; close window, hide (minimize) window, switch to the next/previous virtual
desktop → KWin's own existing shortcut components. Use the real component and action
names KDE already ships (found in the installed packages' own default
`kglobalshortcutsrc` / `.desktop` files inside the guest image) — do not invent action
names; verify each binding actually fires in a live guest before considering it done.

## KRunner: centred floating panel (verified); no real "material" lever found

Scope item 4 ("KRunner: centred floating panel, material driven by tokens"),
investigated live in the guest image (krunner 6.30.0-1, plasma-workspace 6.7.5-1,
kwin 6.7.5-1 — confirmed with `pacman -Q krunner plasma-workspace kwin
plasma-desktop frameworkintegration kirigami-addons`) the same way the KWin
decoration and Overview effect findings above were: by reading KRunner's own
KConfigXT schema and cross-checking it against the compiled KCM's own strings,
then testing live and screenshotting before/after with `harness/spike/
boot_capture.sh`, not by guessing a plausible-sounding key.

**Centred floating panel — real, verified lever: `krunnerrc`
`[General] FreeFloating`.** `/usr/share/config.kcfg/krunnersettingsbase.kcfg`
declares exactly three real keys for KRunner (`FreeFloating` bool default
false, `HistoryBehavior` enum, `RetainPriorSearch` bool default true) — cross-
checked against `kcm_krunnersettings.so`'s own compiled strings, which expose
the standard KConfigXT companions of exactly those three properties and
nothing else. Live, on a genuinely fresh boot with no `krunnerrc` file at all
(so `FreeFloating` at its compiled default, `false`), triggering the real
D-Bus method (`qdbus6 org.kde.krunner /App org.kde.krunner.App.display`, from
`org.kde.krunner.App.xml`) opened KRunner **docked flush against the
underside of the top panel** — horizontally centred, but not floating.
Writing `FreeFloating=true` before the same trigger visibly detached the
popup: still horizontally centred, now also vertically centred with a real
gap above it — a genuine floating panel. Implemented as a static skel file,
`packages/kuura-shell/skel/.config/krunnerrc` (see that file's own header
comment for the full trail); installed by `PKGBUILD`'s `package()` next to
`kwinrc`/`kglobalshortcutsrc`/`kdeglobals`. No token substitution was needed
(the value is a fixed boolean, not derived from `design/tokens.json`), so —
following this document's own rule for when a generator is warranted — this
did not get a sixth `design/generators/` module; it is a plain skel file like
its siblings.

**"Material driven by tokens" — no real, KRunner-specific lever exists in
this build; not implemented, reported per this document's own escalation
rule.** Checked independently rather than assuming the KWin decoration/
Overview precedents above carry over (KRunner uses Plasma's shared dialog
frame system, not KDecoration3 or a kwin effect config group, so the answer
was not assumed either way):
- The kcfg schema above is exhaustive — no opacity/blur/radius/"material" key
  exists for KRunner, confirmed against the KCM binary's own strings.
- `strings -a` on `/usr/bin/krunner` and `/usr/lib/libKF6Runner.so`, grepped
  for `opacity|blur|radius|corner|material|background`, found nothing
  meaningful (an unrelated CLI help string in the former, nothing at all in
  the latter) — KRunner's own code does not parametrise any of this.
- The popup's frame is Plasma's generic, shared dialog background SVG (the
  same asset every popup/tooltip/menu uses), not something KRunner owns.
  Whether it blurs is decided by `Plasma::Theme::blurBehindEnabled()` (found
  by symbol name in `libPlasma.so.6.7.5`) — a **runtime query against the
  compositor's state, not a stored config value** — and KWin's Blur effect is
  already `"EnabledByDefault": true` in its own metadata, so background blur
  already happens globally, out of the box, with nothing to switch on. Its
  only tunable (`kwin_blur_config.so`'s strength/noise/saturation) is a
  compositor-wide multiplier applied to every blurred surface at once — the
  same class of value as the `AnimationDurationFactor` finding below rejected
  as not a real per-component mapping, and treated the same way here.
- No radius/corner key exists anywhere scanned; the popup's corners are
  whatever shape is baked into the shared background SVG asset — the same
  category of finding as the Breeze decoration's boolean-only
  `RoundedCorners` lever, except KRunner does not even have that much of a
  toggle.

`design/tokens.json`'s `material.bg_opacity.menu` (0.7), `material.blur_radius`
(36) and `radius.menu` (10) therefore have no real KRunner-specific lever to
drive in this build. See `packages/kuura-shell/skel/.config/krunnerrc`'s own
header comment for the complete evidence trail (exact commands, exact files
scanned).

**Scope item 5 (Overview effect spacing/animation), closed the same way —
already done, documented at the implementation site rather than here.**
`packages/kuura-shell/skel/.config/kwinrc`'s own "Overview effect tuning"
comment block records the same kind of live investigation: the effect's
compiled KCM (`kwin_overview_config.so`) was scanned for every real
config-key-shaped string and exposes exactly two — `IgnoreMinimized` and
`OrganizedGrid`, both already set — with no spacing/gap/margin/
animation-duration/easing-curve key anywhere in this build. The one
animation-speed lever that does exist, `kdeglobals`' global
`AnimationDurationFactor`, is a unitless multiplier applied to every effect's
own hard-coded duration, not the same kind of value as `design/tokens.json`'s
`motion.duration.base` (an absolute millisecond count) or
`motion.easing_standard` (a cubic-bezier curve) — mapping either onto it was
deliberately not done, to avoid dressing up an approximation as a real
mapping. This is the model the KRunner "material" finding above follows.

## Verification

1. `harness/states.toml`: once real panels/shortcuts/theme exist, remove the
   "the stock X plays the role of the future Y" wording from the state descriptions it
   no longer applies to, and add a GTK application (found by the same "verify, don't
   guess" rule as the shell mechanisms above — Firefox is already in the test image;
   confirm whether its menu bar actually publishes over the global-menu protocol before
   relying on it, and fall back to a small, explicitly test-only GTK text editor if not,
   following V2's precedent for test-only tools).
2. `make vm-image` (rebuilds with `kuura-shell` installed) then `make goldens-review`:
   the visual change is expected and required, never a silent regression. A human
   approves the new goldens (`make goldens-accept`) exactly as in V2 — no tool or agent
   accepts them.

**Done, verified live (2026-09-29):** `harness/states.toml`'s `desktop-empty`,
`menubar-open` and `shelf-hover` describe the real panel now; their click/hover
coordinates were re-measured against a live screenshot of the actually-packaged guest
image, not guessed from the layout generator's token values (`menubar-open`: `[26, 26]`,
confirmed to open Kickoff; `shelf-hover`: `[1089, 1420]`, confirmed to show the hover
tooltip on the first shelf icon). Firefox was confirmed NOT to qualify for the global-menu
DoD (no `com.canonical.AppMenu.Registrar` D-Bus activity when it starts; its own window
shows no traditional menu bar at all). Dolphin (Qt) was re-confirmed against the real V3
panel: its menu renders correctly in the Global Menu widget with no local menu bar.

**Open, not silently closed — GTK half of the DoD is only PARTIALLY satisfied.** Following
this section's own documented fallback, `mousepad` (a classic-menu-bar GTK3 app) plus
`appmenu-gtk-module` (the GTK module that hands a `GtkMenuBar` to KDE's global-menu
registrar; neither was previously in the test image) were added, and a new
`app-menu-gtk` state exercises it. Live evidence is a genuine partial result, reported
rather than rounded up to "done": with `appmenu-gtk-module` loaded, Mousepad's own
in-window menu bar disappears (it hands its menu off) and the registrar/proxy D-Bus
services activate — but the Global Menu WIDGET in the panel still renders nothing for it,
even though the exact same widget correctly shows Dolphin's menu in the same image. The
gap is therefore narrower than "GTK menus do not work" — it is specifically the KWin/
XWayland-side relay from an `appmenu-gtk-module`-exported window to the panel widget — but
was not resolved within this change's scope (mirrors the "Known issue" below: found,
evidenced, bounded, and reported rather than chased indefinitely). See
`harness/states.toml`'s own comment above the `app-menu-gtk` state for the same note kept
next to the state it describes.
