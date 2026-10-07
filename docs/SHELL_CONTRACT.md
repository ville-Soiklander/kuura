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

The second, older mechanism — one GTK theme directory holding both `gtk.css` (light)
and `gtk-dark.css` (loaded instead of it when
`GtkSettings:gtk-application-prefer-dark-theme` is true) — is the standard, documented
GTK convention (not invented here) and is why this document already named a single
`/usr/share/themes/<name>/gtk-4.0/` path rather than two. **It could not be confirmed
visually working in this image at the time, and that was reported rather than papered
over:** GTK4 and libadwaita are not part of the metapackage's dependency graph (nothing
this repository installs pulls them in), and the guest has no network (`-nic none`,
`harness/spike/vm_capture.py`) to add a GTK4 test app for the investigation. A live A/B
test was still possible with GTK3 (present via `firefox`, the test image's browser): a
throwaway theme (`/usr/share/themes/testkuura/gtk-3.0/{gtk.css,gtk-dark.css}`, solid red
vs. solid blue `window` background — an impossible-to-miss difference) was installed and
selected through exactly this mechanism (`~/.config/gtk-3.0/settings.ini`:
`gtk-theme-name=testkuura`, `gtk-application-prefer-dark-theme=1`), then Firefox was
launched fresh. Result: **no visible change at all**, screenshotted, even though the
portal mechanism above demonstrably does change live in the same image. The most likely
explanation was that Firefox's own chrome does not render through the system GTK theme's
CSS at all (a known Firefox/GTK quirk — Firefox has its own theming layer and is
plausibly following the portal instead, consistent with the result) rather than the
`gtk.css`/`gtk-dark.css` swap being broken for an ordinary GTK app — but the tools
available at the time could not tell the two apart, so Firefox was later confirmed to be
the wrong test subject (it does not render its own chrome through GTK theme CSS at all).

**Revised — GTK3 is now shipped, and re-verified with a test subject that actually
renders through GTK theme CSS.** `design/generators/gtk_css.py`'s existing generated
output (unchanged, a locked interface) was confirmed syntactically and semantically
valid GTK3 CSS too, at this project's pinned GTK3 version (`1:3.24.52-1`,
`docs/VERSIONS.md`): the same CSS node names it uses (`window`, `button`, `entry`,
`spinbutton`, `tooltip`, `.csd`, `.card`, `@define-color`, the `transition` shorthand)
exist in both GTK3's and GTK4's own source at the matching tags. `packages/kuura-shell/
PKGBUILD`'s `package()` now installs the exact same two generated files a second time,
under GTK3's own convention, `/usr/share/themes/<name>/gtk-3.0/{gtk.css,gtk-dark.css}`,
alongside a new templated `skel/.config/gtk-3.0/settings.ini.in` (GTK3's counterpart to
the existing `gtk-4.0/settings.ini.in`, same keys, same mechanism). **One known, harmless
limitation:** `popover > contents` (the corner-radius rule for popovers/context menus)
is GTK4-only syntax — GTK3's popover has a single CSS node with no child to select — so
that one rule is a no-op on GTK3: a missing corner-radius on GTK3 context menus and
popovers, not a parse error or any other breakage. Also notable: the bare `menu`
selector in the same CSS is dead on GTK4 (`GtkMenu` was removed there) but alive on
GTK3's classic `GtkMenu` (e.g. a text editor's File/Edit dropdowns), so shipping this
file for GTK3 makes previously-inert CSS become real.

This re-opened the Firefox question properly: `mousepad` (already in the test image for
the global-menu DoD, a real GTK3 app with a classic menu bar) replaces Firefox as the
test subject for `harness/states.toml`'s new `gtk4-widget-factory`-sibling verification
(see that file's own `mousepad`/`gtk4-widget-factory` state comments), and
`gtk4-demos`' `gtk4-widget-factory` (a plain GTK4 demo app with no libadwaita/portal
dependency of its own, see `harness/vm/Containerfile`) was added specifically to isolate
the `gtk-4.0/gtk.css`/`gtk-dark.css` mechanism from the already-proven portal mechanism.

**Live-verified (2026-10-02), two real findings, one of them a correction to how this
mechanism was previously described:**

1. **`mousepad`'s own chrome does not visibly confirm the CSS either way.** With the real
   generated GTK3 theme now shipped (replacing the old throwaway test theme), the
   `app-menu-gtk` state's captured screenshot compares to its pre-existing, approved
   golden with a 80-pixel (0.0022%) difference, comfortably inside tolerance — but that
   diff's bounding box is a ~1px-wide, ~40px-tall sliver matching a text-caret shape, not
   a themed element, so it is more likely blink-phase timing noise than the new CSS
   visibly doing anything. This is not a strong result either way, and the reason is
   structural, not a testing mistake: `app-menu-gtk`'s own design (global-menu DoD)
   deliberately suppresses Mousepad's in-window menu bar via `appmenu-gtk-module`, and
   its window decoration is KWin's own server-side one (already proven to follow the
   colour scheme independently of GTK) — so the one CSS rule that would have been most
   interesting to see on GTK3 specifically (the bare `menu` selector, newly alive per the
   finding above) is never exercised by this state at all, by its own design. Separately
   worth noting for whoever reads this file's rule list again: `gtk_css.py`'s generator
   (`design/generators/gtk_css.py`'s own docstring, re-read against the locked spec) only
   ever emits `border-radius`/font/padding/transition rules — the `@define-color
   token_*` lines it emits are DEFINED but never consumed by any selector — so this CSS
   was never going to visibly recolour anything on GTK3 or GTK4, by design, only resize
   corners and switch the UI font to Inter. A definitive visual confirmation on GTK3
   would need a state that actually opens a classic `GtkMenu` dropdown, which does not
   exist in this harness yet.

2. **The `gtk-dark.css` half of the mechanism is confirmed reachable only as a STATIC,
   per-account default — not as a live follower of the system dark/light toggle — for any
   plain (non-libadwaita) GTK app, and `gtk4-widget-factory` makes this unambiguous.**
   Capturing it with the harness's normal dark-mode application (`plasma-apply-colorscheme
   BreezeDark`, the same live portal mechanism proven above) shows the Plasma top panel
   correctly switch to dark — but the GTK4 app's own window keeps rendering with the LIGHT
   `gtk.css` throughout, unchanged from the light-mode capture. The reason is architectural,
   not a bug in this change: `plasma-apply-colorscheme` only updates the
   `xdg-desktop-portal-kde` broadcast (what libadwaita's `AdwStyleManager` and Qt/KDE apps
   read); it never rewrites the STATIC `gtk-application-prefer-dark-theme=false` key this
   package ships to `~/.config/gtk-{3,4}.0/settings.ini`, and nothing else in this image
   bridges the two (no `kde-gtk-config`-style sync component is installed or depended on).
   So `gtk-dark.css` sits in exactly the same tier as Kvantum's own active-theme selection
   (`~/.config/Kvantum/kvantum.kvconfig`, also a static per-account default, also not
   rewritten by `plasma-apply-colorscheme`) — a user who wants a permanently-dark GTK
   default for non-portal-aware apps has to flip that key themselves (the same method the
   original throwaway A/B test used), it is never a live, system-wide follower. This is a
   real, previously-unstated nuance this document should carry forward clearly: "ships
   gtk-dark.css" does **not** mean "plain GTK apps go dark when the user switches Plasma's
   colour scheme" — only portal-aware (libadwaita) and Qt/KDE apps do that live; everything
   else follows whatever static default is in its own `settings.ini`/`kvconfig`.

(The `gtk4-widget-factory` state itself could not be captured as a passing, comparable
golden in either mode — it never settles inside `settle_timeout_s`, most likely because the
demo keeps the guest CPU busy continuously regardless of visible change, not because
anything is visibly animating; see `harness/states.toml`'s own comment on that state. The
two findings above come from the harness's own `.FAILED.png` diagnostic frames, inspected
directly — real evidence, just not evidence captured through the normal golden pipeline.
See the handback for this change for the exact screenshot paths and descriptions.)

**Revised (2026-10-07) — the dead-colour-tokens finding above is fixed at the code level,
but live re-verification found a SEPARATE, deeper blocker that keeps the fix from showing
on the one GTK4 test subject this harness has. Reported exactly as found, not rounded up.**

`design/generators/gtk_css.py` (the locked interface) now additively references the
colour tokens it already declared but never used: `*` sets `color: @token_text` (inherited
by everything below unless overridden); `window, .csd` sets `background-color:
@token_window`; `button`, `entry, spinbutton`, `popover > contents, menu` and `.card` each
set `background-color: @token_surface`; `tooltip` sets its own `background-color:
@token_tooltip_bg` / `color: @token_tooltip_text` pair. No new selectors, no new tokens —
exactly the four kinds of rule the DoD-era finding above named as missing. `design/tests/
test_gtk_css.py` now asserts every rule block exactly (property order included), and a new
`test_render_real_tokens_colors_actually_referenced` test fails loudly if a future change
ever lets a declared colour token go unused again. 851 pytest passed + 4 skipped (850+4
before this session, one new test added here) / ruff / forbidden-terms clean.

**Regression check: no visible change anywhere else.** A full `make repo` → `make
vm-image` → capture-all-states → compare-against-the-20-approved-goldens cycle (the same
method the previous GTK3/4 session used) found all 9 non-GTK states and `app-menu-gtk`
still passing at effectively the same tiny tolerances as before the change (e.g.
`app-menu-gtk` dark: 80px/0.0022%, the same caret-blink sliver already documented above,
not a new or larger diff) — the four added `background-color`/`color` rules do not leak
into any Qt/KDE surface anywhere in the 20 regression states.

**`gtk4-widget-factory`, captured the same way as before (the `.FAILED.png` diagnostic,
since it still never settles — see the paragraph above): window background, button fill
and entry fill are pixel-identical between light and dark capture (`#f6f5f4` window
background, sampled at six different empty-gutter points in both modes; `#f8f7f7`
togglebutton; `#faf9f8` entry) — and NEITHER value is the token this change just wired up
(`color.light.window` = `#F2F4F7`, `color.dark.window` = `#15181C`). The colour fix's own
rules are not visibly reaching this app in the harness's normal capture, in either mode.**

Investigated rather than left as an unexplained mismatch: `org.freedesktop.portal.Settings
Read ss org.gnome.desktop.interface gtk-theme`, called live inside the guest the same way
this document's own "Dark mode" section above already calls `Settings.ReadAll` for
`org.freedesktop.appearance`, answers `"Adwaita"` — not `"kuura"`, regardless of
`~/.config/gtk-4.0/settings.ini`'s `gtk-theme-name=kuura` (confirmed present and correct on
disk, byte-for-byte the packaged file). GTK4's own documented portal integration (added so
Wayland sessions without XSettings can still learn the configured GTK theme) consults this
exact portal key, and appears to take priority over the local `settings.ini` value when the
portal answers at all — `xdg-desktop-portal-kde` is the only portal backend this image
installs (`packages/kuura-desktop/PKGBUILD`), so it is the source of this fixed `"Adwaita"`
answer, most likely a KDE-side default/fallback for a GNOME-namespaced setting KDE has no
native equivalent of, not anything this project's own packages configure.

**Confirmatory experiment (proves the generated CSS itself is correct, and separately
reveals a second, pre-existing scope gap):** launching `gtk4-widget-factory` with
`GTK_THEME=kuura` forced in its environment — GTK's own documented override, which bypasses
both `settings.ini` and the portal lookup — produced window/entry background pixels of
EXACTLY `#f2f4f7` and `#ffffff`, this project's real `color.light.window` and
`color.light.surface` token values, byte for byte. This confirms the generated CSS is
semantically correct and ready to work the moment GTK4 actually loads it. The same forced
capture also showed every button, entry and combo box rendering with **no visible border**
at all (compare the bordered, boxy look of the normal/portal-blocked capture against the
flat, borderless one under the forced theme) — because `gtk_css.py`'s file, by design, only
ever supplied colour/radius/font/transition, never border declarations, which the GTK4
default ("Adwaita") stylesheet it has been silently falling back to was supplying all
along. This is not something this change introduced — the same gap existed, invisibly, in
every previous version of this file — it only became visible now that a real theme file was
forced to load as the complete stylesheet for the first time.

**Resolved (2026-10-07) — the human chose, explicitly, the `GTK_THEME` env-var candidate
named below, plus a border declaration for `gtk_css.py`; both are now shipped and
live-verified against a real rebuilt image, with NO manual override anywhere.**
`packages/kuura-shell/skel/.config/plasma-workspace/env/15-gtk-theme.sh.in` (templated to
`export GTK_THEME=kuura` at package-build time, same `sed`+`mktemp` pattern as this
package's other three skel templates) installs to `/etc/skel/.config/plasma-workspace/env/
15-gtk-theme.sh`, sourced by the Plasma session startup script at login — the same real,
documented GTK environment-variable override confirmed in the previous revision's forced
experiment, now shipped as a normal product file instead of a manual test override.
`gtk_css.py` also gained `border: 1px solid @token_separator;` on `button`, `entry,
spinbutton`, `popover > contents, menu` and `.card` (the second gap the forced experiment
found: these surfaces sat on the window background with no border at all).

**It works — confirmed on `gtk4-widget-factory` with pixel sampling, no `GTK_THEME`
override anywhere.** A fresh `make repo` → `make vm-image` → capture cycle (no manual
environment tampering, just the shipped package) produced, for the first time, real
`.png` captures of this state in both modes — it settled normally this run
(`status: ok`, ~9–13s), unlike both previous sessions' repeated "never settles" finding;
`harness/states.toml`'s own comment on this state should be read as "usually fails to
settle," not "always." A full-image colour histogram (`harness.shots.pngio.read_png`,
every 2nd pixel sampled) found, in the **light** capture: `#f2f4f7` at 71.63%
(`color.light.window`, window background merged with the desktop's own same-coloured
background), `#ffffff` at 9.97% (`color.light.surface`, button/entry/popover/card fill),
and `#d5dbe3` at 1.09% (`color.light.separator`, the new border) — all three matching
this project's real tokens byte-for-byte, no trace of the old `"Adwaita"` fallback. The
border is real and visible, closing the second gap too.

**The already-documented "static, not live dark/light toggle" limitation is confirmed to
still hold, with exact arithmetic, not just a visual impression.** In the **dark**
capture, `#ffffff` (surface) and `#d5dbe3` (separator) appear at the IDENTICAL sampled
pixel counts as light (91926 and 10000 respectively, both strides) — the app's own
button/entry/border fill is bit-for-bit unchanged between modes. `#f2f4f7` still
dominates at 66.86% (down from 71.63%), and a new colour appears only in dark,
`#15181c` (`color.dark.window`) at 4.77% — sampling the screen corners directly
((10,10), (1280,10), (2550,10), well outside the app window) gives exactly `#f2f4f7` in
light and exactly `#15181c` in dark, confirming this 4.77% is the DESKTOP background
correctly following the live portal mechanism, while the 66.86% remaining `#f2f4f7` is
the GTK window's OWN background still rendering light. The arithmetic closes cleanly:
71.63% − 66.86% ≈ 4.77%, i.e. the desktop's own area in the light capture (which happens
to share `color.light.window`'s exact value, making it indistinguishable from the GTK
window there) is the same area that reads `#15181c` once the desktop itself goes dark.
**Cause, as before:** `gtk-application-prefer-dark-theme=false` in
`gtk-4.0/settings.ini` is a static key written once from `/etc/skel`, never rewritten by
`plasma-apply-colorscheme`, so the app keeps loading `gtk.css` (not `gtk-dark.css`)
regardless of Plasma's live mode — `GTK_THEME` fixes ACTIVATION (which theme directory
loads at all) but does not change this separate, already-known static-default mechanism.
A reader of this section should not assume the activation fix also made this live.

**Open regression found by the same rebuild, reported rather than filed away — a real
decision point, not resolved here.** Comparing the full capture (not just
`gtk4-widget-factory`) against the 20 approved goldens found 3 failing states, all
perfectly reproducible (identical pixel counts and bounding boxes across two independent
capture runs, so none of this is capture-to-capture noise):

1. **`app-menu-gtk` (mousepad, GTK3), both modes, 33.33% of pixels differing, identical
   stats in light and dark.** Pixel sampling pinpoints it: the text-editing area's
   background is `#eeeeec` where the approved golden has `#ffffff`. Likely cause:
   `GTK_THEME` is a plain, long-standing GTK environment-variable override honoured by
   GTK3 too, not just GTK4, so it now makes mousepad genuinely adopt this project's
   theme as its sole active stylesheet,
   the same way it does for GTK4 — but `gtk_css.py` only ever defines this project's own
   `@token_*` names, never GTK's OWN standard named colours (`@theme_base_color`,
   `@theme_bg_color`, etc.) that GTK's built-in default CSS uses for unstyled nodes like
   a `GtkTextView`'s `view` node. Before this session, something left that node with a
   sensible (white) default; now it falls back to a flat grey. Not confirmed by reading
   GTK's own source in this session — stated as the likely mechanism, not a proven one.
2. **`browser-window` (Firefox), both modes, ~5.3–5.6%.** The diff is confined to the
   window's own edge/shadow and the tab-bar/address-bar text, not the page content
   (consistent with the already-documented "Firefox's own chrome does not render through
   system GTK theme CSS" finding for its CONTENT, but Firefox is still a GTK3-linked
   process, so its native window border/CSD handling is a plausible `GTK_THEME` path too
   — not confirmed).
3. **`menubar-open`, dark mode only, 1.33%** (light passes cleanly, both capture runs).
   This is Plasma's own Kickoff launcher — pure Qt/QML, no GTK dependency of any kind.
   No causal mechanism tying it to this change was found; the diff pattern (nearly every
   text label affected, solid fills mostly not) looks like a uniform sub-pixel shift
   rather than a colour change, but the cause is unidentified.

All three are shipped, uncommitted, exactly as built — this document is not recommending
a fix or a revert, only reporting what a real rebuild with the human-approved change
produced, including a plausible but unconfirmed mechanism for #1 and two genuinely open
questions (#2, #3) a human should see before this goes further.

(Capture methodology note: the previous revision found that capturing
`gtk4-widget-factory` then immediately switching mode in the SAME boot made every
following dark-mode state fail to settle. This session's regression capture again used
two separate boots, one per mode, as a precaution — but this run `gtk4-widget-factory`
itself settled normally in both boots (see above), so that specific interaction could not
be re-observed one way or the other this time. Worth a line in `harness/states.toml`'s
own comments if `gtk4-widget-factory` is ever reordered to not be the last state before a
mode switch.)

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

## Animation curves (motion tokens)

Vaihe 6 ("sovellustason viimeistely") asked to unify animation curves everywhere
using `design/tokens.json`'s motion tokens (`motion.duration.{instant,fast,base,
slow}` = 100/180/260/400ms, `motion.easing_standard` = a cubic-bezier string,
`motion.easing_spring` = {mass,stiffness,damping}). Investigated the same way the
KWin decoration, Overview and KRunner findings above were — by reading the real,
pinned KDE/Qt source (kwin 6.7.5, kirigami/qqc2-desktop-style 6.30.0, fetched
from invent.kde.org at those exact tags), not by assuming a plausible-sounding
config key exists.

**1. One real, exact lever wired up: `kwinrc [Effect-slidingpopups]
SlideInTime`/`SlideOutTime`.** `src/plugins/slidingpopups/slidingpopups.cpp` at
the pinned kwin v6.7.5 tag, `SlidingPopupsEffect::reconfigure(ReconfigureFlags
flags)`:
```cpp
m_slideInDuration = animationTime(SlidingPopupsConfig::slideInTime() != 0
    ? std::chrono::milliseconds(SlidingPopupsConfig::slideInTime()) : 200ms);
m_slideOutDuration = animationTime(SlidingPopupsConfig::slideOutTime() != 0
    ? std::chrono::milliseconds(SlidingPopupsConfig::slideOutTime()) : 200ms);
```
`SlideInTime`/`SlideOutTime` are real, absolute-millisecond `kwinrc` keys (0 means
"use the compiled 200ms default"; any other value is used as-is). Because
`design/tokens.json`'s `motion.duration.*` values are already absolute
millisecond counts, writing `motion.duration.fast` (180ms) into this key is a
lossless, non-approximated mapping — unlike the two cases below. Implemented in
`design/generators/kwin_motion.py` (`render_slidingpopups_fragment()`), wired
into `design/generate.py`'s `generate()` as the 14th output file
(`kwin/slidingpopups.ini`), and appended onto the static
`packages/kuura-shell/skel/.config/kwinrc` by `PKGBUILD`'s `package()` step
(plain concatenation — see that PKGBUILD's own comment for why this is safe).
`SlideInTime`/`SlideOutTime` drive `KWindowEffects::slideWindow()`, the
mechanism various `PlasmaQuick::Dialog`-based popups use to slide in from an
edge — a different, unrelated mechanism from the separate SlidingNotifications
effect, which hardcodes its own curve (see point 3 below).

**2. `kdeglobals [KDE] AnimationDurationFactor`: real and live, but
deliberately NOT used.** Confirmed real at kwin v6.7.5,
`src/kcms/animations/animationskdeglobalssettings.kcfg`:
```xml
<entry name="animationDurationFactor" key="AnimationDurationFactor" type="Double">
  <label>Animation speed</label>
  <default>1.0</default>
</entry>
```
And confirmed live in the real consumer chain, `frameworks/qqc2-desktop-style`
at the pinned v6.30.0 tag. `kirigami-plasmadesktop-integration/
animationspeedprovider.cpp` reads the exact same `kdeglobals` key:
```cpp
m_animationSpeedModifier = std::max<double>(0.0, generalCfg.readEntry(u"AnimationDurationFactor"_s, 1.0));
```
and `kirigami-plasmadesktop-integration/plasmadesktopunits.cpp` (the class
`PlasmaDesktopUnits`, extending `Kirigami::Platform::Units`, which is what
every Kirigami-based Plasma surface gets its animation durations from) applies
it as a single multiplier to one base duration, then derives the other three
from fixed ratios off that same base:
```cpp
constexpr int defaultLongDuration = 200;
// ...
longDuration = qRound(longDuration * animationSpeedModifier);
setVeryShortDuration(longDuration / 4);
setShortDuration(longDuration / 2);
setLongDuration(longDuration);
setVeryLongDuration(longDuration * 2);
```
With the factor at its default 1.0, this is 50/100/200/400ms — a fixed
**1:2:4:8** ratio off a 50ms unit. `design/tokens.json`'s own four buckets
(100/180/260/400ms) are a fixed **1:1.8:2.6:4.0** ratio off its own smallest
bucket (`instant`) — a different shape, not a scaled copy of Kirigami's. One
unitless scalar cannot turn one fixed ratio into the other: picking a factor
that makes `AnimationDurationFactor × 200ms` land exactly on `base` (260ms,
factor 1.3) leaves `veryShort` at `260/4` = 65ms against this project's
`instant` (100ms) — a 35% miss — and `veryLong` at `260×2` = 520ms against
`slow` (400ms) — a 30% miss, in the opposite direction from the first. Picking
any other bucket to match exactly just moves the 30–100% drift onto the other
three. That is an approximation dressed up as a real mapping, which this
project's own standing rule (see `packages/kuura-shell/skel/.config/kwinrc`'s
"Effect-overview" comment, which rejected the same lever for the same reason
first) declines to ship. `design/generators/kwin_motion.py`'s own module
docstring records this same reasoning at the implementation site.

**3. `motion.easing_standard` / `motion.easing_spring`: confirmed no config
surface exists anywhere in the real stack surveyed.** Every real curve shape
found in the pinned source is a literal, hardcoded value, never read from any
config file. Example, kwin v6.7.5's Overview effect,
`src/plugins/overview/qml/Main.qml` (three separate `NumberAnimation` blocks,
all identical in this respect):
```qml
NumberAnimation {
    duration: effect.animationDuration
    easing.type: Easing.OutCubic
}
```
`easing.type` is the literal Qt Quick enum `Easing.OutCubic`, compiled into the
QML; there is no property, kcfg entry or config group anywhere in this file (or
in `slidingpopups.cpp`'s own curve, a plain linear interpolation with no easing
property at all) that a packager could point at `motion.easing_standard`'s
cubic-bezier control points or `motion.easing_spring`'s mass/stiffness/damping
triple. Reaching either would mean patching and recompiling upstream
KWin/Kirigami, out of scope for a config-only package like this one. Neither is
implemented; this is reported as confirmed-not-achievable, not silently
dropped.

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
