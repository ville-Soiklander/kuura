# kuura-decoration: interface notes (phase 1)

Own KDecoration3 window-decoration plugin that replaces the Aurorae QML theme
(`design/generators/aurorae.py`, docs/SHELL_CONTRACT.md "Window decoration"). It keeps the
QML theme's look and adds what QML could not do: rounded **bottom** corners via the
protected `KDecoration3::Decoration::setBorderRadius()`.

Status: interface locked (headers in `src/`); phase 2 implemented (all `.cpp` files,
`metadata.json.in`, `CMakeLists.txt`, `PKGBUILD` with `check()` running the three ctest
unit tests). Section 7 (live checks) is still open.

## 1. Files

| File | Role | Phase |
|---|---|---|
| `src/geometry.h` | Qt-free layout logic (borders, title bar, buttons, caption, radius, glyph shapes) | locked |
| `src/palette_logic.h` | Qt-free colour logic (light/dark, token palette, disc colour, dimming, glyphs) | locked |
| `src/shadow_logic.h` | Qt-free shadow parameters, falloff and nine-slice mask | locked |
| `src/decoration.h` | `Kuura::Deco::Decoration : KDecoration3::Decoration` | locked |
| `src/button.h` | `Kuura::Deco::Button : KDecoration3::DecorationButton` | locked |
| `src/geometry.cpp`, `src/palette_logic.cpp`, `src/shadow_logic.cpp` | pure logic; only these include `<tokens.h>` / `<token_colors.h>` | to do |
| `src/decoration.cpp`, `src/button.cpp` | Qt/KDecoration3 glue | to do |
| `src/plugin.cpp` | `K_PLUGIN_FACTORY_WITH_JSON` (see bottom of `decoration.h`) | to do |
| `src/metadata.json.in` | configure-time template (section 4) | to do |
| `CMakeLists.txt`, `PKGBUILD` | build and package (sections 3, 5) | to do |
| `tests/*_test.cpp` | unit tests (section 6) | to do |

Suggested split for delegation: (a) the three pure-logic `.cpp` files, (b) their tests by a
different agent, (c) `decoration.cpp` + `button.cpp` + `plugin.cpp` + `metadata.json.in`,
(d) CMakeLists + PKGBUILD + the out-of-package changes (section 9). (a) and (b) can run in
parallel; (c) needs (a); (d) can start with (a).

## 2. Prerequisite in `design/` (not done here)

`cpp/tokens.h` already holds every number this package needs
(`kDecorationTitlebarHeight`, `kDecorationButtonDiameter`, `kDecorationButtonSpacing`,
`kDecorationButtonInset`, `kDecorationGlyphStroke`, `kDecorationShadowSize`,
`kRadiusWindow`, `kStrokeHairline`, `kSpacingGutter`; namespace `Kuura::Tokens`).
It does **not** hold colours. The exact spec of the missing `cpp/token_colors.h`
(new `cpp_header.render_colors(tokens)`, written by `design/generate.py`; `tokens.h` stays
byte-identical so kuura-frost is unaffected) is in the comment block at the top of
`src/palette_logic.h`. Needs a test in `design/tests/` like the existing cpp_header tests.

## 3. CMakeLists.txt plan

```
cmake_minimum_required(VERSION 3.16)
project(kuura-decoration LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)            # KDecoration3 headers use operator<=> (BorderRadius)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)                 # Q_OBJECT classes + "plugin.moc"
set(CMAKE_EXPORT_COMPILE_COMMANDS ON) # clang-tidy

find_package(ECM 6.0.0 REQUIRED NO_MODULE)   # version needed, see kuura-frost CMakeLists
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
include(KDEInstallDirs)
include(KDECMakeSettings)   # sets CMAKE_SHARED_MODULE_PREFIX "" (=> no "lib" prefix) and
                            # BUILD_TESTING (default ON) + include(CTest)
find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(KF6CoreAddons REQUIRED)         # KPluginFactory / K_PLUGIN_FACTORY_WITH_JSON
find_package(KDecoration3 REQUIRED)          # target KDecoration3::KDecoration,
                                             # variable KDECORATION_PLUGIN_DIR

# Product name from the environment, passed by the PKGBUILD as -DDISTRO_NAME=...
set(DISTRO_NAME "" CACHE STRING "Product name (DISTRO_NAME in .env.example)")
if(NOT DISTRO_NAME MATCHES "^[a-z0-9_-]+$")
    message(FATAL_ERROR "DISTRO_NAME must be lowercase letters, digits, '_' or '-'")
endif()
set(KUURA_DECORATION_PLUGIN_ID "${DISTRO_NAME}.decoration")
configure_file(src/metadata.json.in "${CMAKE_CURRENT_BINARY_DIR}/metadata.json" @ONLY)

# Pure logic, linked into the plugin AND the tests (PIC because the plugin is a MODULE).
add_library(kuura_decoration_logic STATIC
    src/geometry.cpp src/palette_logic.cpp src/shadow_logic.cpp)
set_target_properties(kuura_decoration_logic PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(kuura_decoration_logic
    PUBLIC  "${CMAKE_CURRENT_SOURCE_DIR}/src"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/generated/cpp")   # <tokens.h>, <token_colors.h>

add_library(kuura_decoration MODULE src/decoration.cpp src/button.cpp src/plugin.cpp)
set_target_properties(kuura_decoration PROPERTIES OUTPUT_NAME "${KUURA_DECORATION_PLUGIN_ID}")
# moc must find metadata.json named in K_PLUGIN_FACTORY_WITH_JSON:
target_include_directories(kuura_decoration PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(kuura_decoration PRIVATE
    kuura_decoration_logic Qt6::Core Qt6::Gui KF6::CoreAddons KDecoration3::KDecoration)
install(TARGETS kuura_decoration
        DESTINATION "${KDE_INSTALL_PLUGINDIR}/${KDECORATION_PLUGIN_DIR}")

if(BUILD_TESTING)
    find_package(Qt6 REQUIRED COMPONENTS Test)
    # one executable per module: tests/geometry_test.cpp, tests/palette_logic_test.cpp,
    # tests/shadow_logic_test.cpp; add_test() each; link kuura_decoration_logic Qt6::Test
    # (Qt6::Gui only where QColor/KDecoration3::snapToPixelGrid is used for comparison)
endif()
```

Notes:
- Install path resolves to `/usr/lib/qt6/plugins/org.kde.kdecoration3/<id>.so`, the same
  directory as `org.kde.breeze.so` and `org.kde.kwin.aurorae.so` in the pinned snapshot.
  `KDECORATION_PLUGIN_DIR` is set to `org.kde.kdecoration3` by the installed
  `KDecoration3Config.cmake` (kdecoration `KDecoration3Config.cmake.in`).
- `add_library(MODULE)` like Breeze (breeze `kdecoration/CMakeLists.txt`), not
  `kcoreaddons_add_plugin()`: avoids the `BUILD_SHARED_LIBS` trap documented in
  kuura-frost's CMakeLists. Either works; pick one and say why in a comment.
- Test framework: QtTest (part of `qt6-base`, already a dependency; no new package and no
  licence check needed). The project's C++ rule names GoogleTest only as an example;
  using it would add a package and a `lisenssitarkistus`.
- `generated/` is written by the PKGBUILD's `design.generate` step, exactly like
  kuura-frost (`generated/cpp/tokens.h`). Without it the build fails loudly (intended).

## 4. Plugin metadata (`src/metadata.json.in`)

```json
{
    "KPlugin": {
        "Id": "@KUURA_DECORATION_PLUGIN_ID@",
        "Name": "<Display name, e.g. product name + ' Round Buttons'>",
        "Description": "Round title-bar buttons, follows the colour scheme",
        "License": "<SPDX id of this package>",
        "EnabledByDefault": true
    },
    "org.kde.kdecoration3": {
        "blur": false,
        "recommendedBorderSize": "Normal"
    }
}
```

- Keys from breeze v6.7.5 `kdecoration/breeze.json` (`KPlugin`, `org.kde.kdecoration3`
  with `blur`, `recommendedBorderSize`) and kwin v6.7.5
  `src/decorations/decorationbridge.cpp` `loadMetaData()` (reads the `org.kde.kdecoration3`
  object: `recommendedBorderSize`, and `themes`/`defaultTheme` via `findTheme()`).
- **No `themes` key**: we are a single-look plugin. Without `themes: true` KWin never
  reads or passes `theme=` (`findTheme()` returns early).
- `recommendedBorderSize: "Normal"` matches our 4 px default; with Breeze's `"None"` the
  settings page labels its first entry "Theme default (No window borders)", the confusing
  label noted in the skel kwinrc comment.
- No `X-KDE-ConfigModule`: there is no settings page for this decoration.
- The display name is built from `DISTRO_NAME` in CMake (title-cased), like aurorae.py does
  for the QML theme; do not hard-code the product name.

## 5. Plugin id, kwinrc and PKGBUILD

**Plugin id (proposal):** `${DISTRO_NAME}.decoration` (here `kuura.decoration`), set at
configure time as both the file name `kuura.decoration.so` and `KPlugin.Id`.
KWin finds plugins with `KPluginMetaData::findPluginById("org.kde.kdecoration3", id)`
(decorationbridge.cpp, `initPlugin()`); the id is `KPlugin.Id`, which we set explicitly so
it does not depend on the file-name fallback. KDE's own ids are reverse-DNS
(`org.kde.breeze`); a reverse-DNS id needs a domain the project controls, so the plain
`<name>.decoration` is proposed instead. Alternative if the owner prefers:
`org.<name>.decoration`.

**kwinrc** (`packages/kuura-shell/skel/.config/kwinrc`, group `[org.kde.kdecoration2]`;
KWin 6.7.5 still reads this group name: decorationbridge.cpp `s_configKeyName`):
```
library=@NAME@.decoration
```
and **remove** `theme=@NAME@-decoration` (ignored by a plugin without `themes`, keeping it
only misleads). `ButtonsOnLeft=XIA`, `ButtonsOnRight=`, `BorderSizeAuto=false` stay.
Fallback when the plugin fails to load: KWin tries `org.kde.breeze`, then
`org.kde.kwin.aurorae` (decorationbridge.cpp `init()`, `s_defaultPlugin`,
`s_fallbackPlugin`), so `[Windeco] RoundedCorners=true` stays useful as Breeze's fallback.

**PKGBUILD** (same layout as `packages/kuura-frost/PKGBUILD`):
- `pkgname="${DISTRO_NAME:?DISTRO_NAME must be set}-decoration"`, `arch=('x86_64')`
  (native code against a pinned library ABI).
- `depends=('kwin' 'kdecoration' 'qt6-base' 'kcoreaddons')`: kdecoration
  (`libkdecorations3.so`), Qt and KF6CoreAddons are linked directly, so they are listed
  directly instead of relying on kwin's dependency list.
- `makedepends=('cmake' 'ninja' 'extra-cmake-modules' 'python')` plus the runtime ones
  (makepkg installs `depends` for building too). No `vulkan-headers`/`mesa`: we do not link
  `KWin::kwin`.
- `license=`: the plugin links only LGPL libraries (kdecoration, Qt, KF6CoreAddons), so the
  project default `GPL-3.0-or-later` is possible; owner to confirm (kuura-frost is
  GPL-2.0-or-later because it links KWin itself).
- `build()`: `( cd "$srcdir/../../.." && python3 -m design.generate --out-dir
  "$srcdir/../generated" --name "$DISTRO_NAME" )`, then
  `cmake -S . -B build -G Ninja -DCMAKE_INSTALL_PREFIX=/usr -DDISTRO_NAME="$DISTRO_NAME"
  -DBUILD_TESTING=ON` and `cmake --build build`.
- `check()`: `QT_QPA_PLATFORM=offscreen ctest --test-dir build --output-on-failure`
  (the pure-logic tests need no platform at all; the variable only protects tests that
  touch QtGui).
- `package()`: `DESTDIR="$pkgdir" cmake --install build`.
- `kuura-shell` should depend on (or `kuura-desktop` should pull in) this package, because
  the skel kwinrc names its plugin; `build/build_repo.sh` orders local packages by
  `depends` automatically.

## 6. Unit tests to write (against the locked headers only)

Write them from the headers' contracts, not from the implementation. Each validation rule
gets both sides of its limit.

`tests/geometry_test.cpp`
- `tokenMetrics()` equals the `Kuura::Tokens` constants; `isValid(tokenMetrics())`.
- `isValid()`: each range at both sides (titleBarHeight 23/24/64/65, buttonDiameter
  7/8/20/21, buttonSpacing -1/0/24/25, buttonInset -1/0/32/33, glyphStroke 0.49/0.5/3/3.01,
  shadowSize -1/0/32/33, cornerRadius == titleBarHeight valid and +1 invalid,
  hairline 0 invalid, NaN/inf invalid, diameter > titleBarHeight invalid).
- `frameBorders()`: all three presets x maximized/not; top always titleBarHeight.
- `resizeOnlyBorders()`: presets x maximizedH/V combinations; top always 0.
- `titleBarRect()`: maximized vs floating (y = kTopResizeStrip, x = borders.left), width
  never negative for a tiny decorationWidth.
- `buttonGroupWidth()`: 0, 1, 3 buttons; spacing 0.
- `buttonGroupOrigin()`: left/right, vertical centring with floor (odd difference, e.g.
  bar 36 / disc 13 -> y 11).
- `buttonRects()`: count, spacing, all on one row; empty for 0.
- `hoverZone()`: slack on both sides, full bar height; empty group -> empty zone.
- `contains()`: half-open edges (left/top inside, right/bottom outside), empty rect.
- `captionRect()`: symmetric padding with only a left group; width clamps to 0.
- `cornerRadius()`: 0 when maximized.
- `snapToPixelGrid()`: scale 1, 1.25, 1.5, 2; scale 0/negative/NaN treated as 1; equals
  `KDecoration3::snapToPixelGrid()` (header-only, `<KDecoration3/ScaleHelpers>`).
- `outlineThickness()`: never below 1/scale.
- `glyphBars()`/`glyphTriangles()`: counts per glyph, centred on the disc, lengths per
  factor, triangles scaled (disc 12 -> grid values unchanged, disc 24 -> doubled).

`tests/palette_logic_test.cpp`
- `unpackRgba()` byte order; `tokenPalette()` matches tokens (light/dark close etc., glyph
  ink = dark window in both modes, shadow alpha 0x33/0x66).
- `hslLightness()` and `darker()` against `QColor::lightnessF()` / `QColor::darker(128)`
  for a set of colours including grey, black, white and the three disc colours (+-1 step);
  `darker()` with factor 0, negative, NaN returns the input; alpha preserved.
- `modeForBackground()`: both project window colours; threshold both sides (lightness just
  under / at 0.5).
- `discColor()`: full table kind x {active, inactive} x {groupHovered} x {pressed};
  Spacer -> nullopt; pressed wins over idle.
- `buttonOpacity()`, `showGlyph()`, `glyphFor()` (restore only for Maximize when
  windowMaximized; None when not shown; Spacer always None).

`tests/shadow_logic_test.cpp`
- `shadowParams()` from tokens (16 -> offsetY 4, extent 12); shadowSize 0 -> extent 0;
  rounding of offsetY as specified in the header (2 -> 1, 6 -> 2, 16 -> 4).
- `shadowPadding()` values; extent < offsetY -> top 0.
- `shadowAlpha()`: peak at 0, 0 at extent, strictly decreasing between, peak 0 -> 0.
- `roundedRectSignedDistance()`: centre negative, edge 0, corner diagonal, radius clamp.
- `renderShadowImage()`: dimensions = core + padding; innerShadowRect position; alpha 0 at
  the core centre (cut-out); left/right symmetry; edge row identical along the stretched
  column (nine-slice validity); value just below the bottom edge close to
  `255 * peak`; disabled shadow -> empty image.

Optional, not required for phase 2: an instantiation test of the real `Decoration` with a
mock `KDecoration3::DecorationBridge` (private API, CMake target
`KDecoration3::KDecoration3Private`, headers `<KDecoration3/Private/...>` are in the
pinned package; kdecoration's own `autotests/mockbridge.*` show the pattern). It would
verify borders/radius/title bar/button positions through the real framework, at the cost
of depending on a private API.

## 7. What can only be verified live (guest image, KWin 6.7.5)

1. `kuura.decoration` is listed in System Settings > Window Decorations with its name and a
   button preview (proves the `registerPlugin<Button>()` path); it is selected on a fresh
   account; `journalctl --user -b | grep -i decoration` shows no "Could not locate
   decoration plugin" / "Error loading plugin" (decorationbridge.cpp warnings).
2. Discs on the left, close first, vertically centred; glyphs on all three while hovering
   any of them or the gaps; grey discs on an unfocused window, colours on hover; pressed
   darkens; maximize disabled and dimmed on a fixed-size window; restore glyph when
   maximized; clicks close / minimize / maximize; middle/right click on maximize.
3. **All four corners rounded**, client content clipped at the bottom corners (a terminal
   with a coloured background shows it best); hairline follows the rounded outline.
4. `plasma-apply-colorscheme <name>-dark` turns title bar, caption, outline and shadow
   dark on open windows with no other step; back to light likewise.
5. Shadow visible around floating windows, absent when maximized; compare its strength
   with the screenshot of the QML theme; no shadow through translucent windows.
6. Title bar drags and double-click maximizes; top edge 4 px strip resizes; side and
   bottom borders and the corners resize; "No borders"/"No side borders" still resizable.
7. Fractional scaling (1.25, 1.5): no seams, outline at least one device pixel.
8. X11 session without compositing (if supported at all in the image): square plain frame,
   no artefacts (`isAlphaChannelSupported()` false path).
9. Screenshot harness (`make shots`) passes with the new plugin.

## 8. API facts (kdecoration v6.7.5 unless noted; Breeze/KWin v6.7.5 read as reference)

| Fact | Source |
|---|---|
| Plugin namespace `org.kde.kdecoration3`; KCM namespace `org.kde.kdecoration3.kcm` | `KDecoration3Config.cmake.in` (`KDECORATION_PLUGIN_DIR`, `KDECORATION_KCM_PLUGIN_DIR`); kwin `src/decorations/decorationbridge.cpp` `s_pluginName` |
| kwinrc group still `org.kde.kdecoration2`, keys `library`, `theme`, `NoPlugin`; default plugin `org.kde.breeze`, fallback `org.kde.kwin.aurorae` | kwin `decorationbridge.cpp` (`s_configKeyName`, `readPlugin()`, `readTheme()`, `init()`) |
| Factory call `create<KDecoration3::Decoration>(window, QVariantList{args})`, args map with `bridge` (+`theme`); then `setSettings()`, `create()`, `init()` | kwin `decorationbridge.cpp` `createDecoration()` |
| Settings page creates buttons via `create<KDecoration3::DecorationButton>(parent, {type, decoration})` | kwin `src/kcms/decoration/declarative-plugin/previewbridge.cpp` `createButton()` |
| `K_PLUGIN_FACTORY_WITH_JSON(..., registerPlugin<Decoration>(); registerPlugin<Button>();)` | breeze `kdecoration/breezedecoration.cpp` |
| `Decoration(QObject *parent, const QVariantList &args)` protected ctor; `virtual bool init() = 0`; `virtual void paint(QPainter *, const QRectF &) = 0` | `src/decoration.h` |
| Protected setters `setBorders`, `setResizeOnlyBorders`, `setBlurRegion`, `setTitleBar`, `setOpaque`, `setShadow`, `setBorderRadius`, `setBorderOutline`; virtual hover/mouse handlers | `src/decoration.h` |
| `BorderRadius(topLeft, topRight, bottomRight, bottomLeft)` (note the order) and `BorderOutline(thickness, color, radius)`; double-buffered via `DecorationState`/`setState()` | `src/decoration.h`, `src/decoration.cpp` (`setBorderRadius()`, `setState()`) |
| KWin clips decoration + client to the frame with the radius | kwin `src/scene/windowitem.cpp` `updateBorderRadius()`; `src/window.cpp` `updateDecorationBorderRadius()`; `src/scene/itemrenderer_opengl.cpp` corner stack |
| Outline drawn outside the frame, inflated by thickness | kwin `src/scene/outlinedborderitem.cpp`; `src/scene/decorationitem.cpp` `updateOutline()` |
| Breeze sets radius/outline in `recalculateBorders()`, title bar in `updateTitleBar()` (inset from top for resizing), `setOpaque` on `maximizedChanged`, shadow in `updateShadow()` with static shared objects, re-snaps on `nextScaleChanged` | breeze `breezedecoration.cpp` |
| Title-bar / foreground colours: `DecoratedWindow::color(ColorGroup, ColorRole)`; KWin uses `[Colors:Header]` if present, else `[WM]`; repaint on palette change | kdecoration `src/decoratedwindow.h`; kwin `src/decorations/decorationpalette.cpp`, `src/window.cpp` (paletteChanged -> triggerDecorationRepaint), `src/decorations/decoratedwindow.cpp` |
| Button groups read left/right lists from settings, recreate on change, lay out visible buttons with spacing, mirror for RTL | `src/decorationbuttongroup.cpp` (ctor, `Private::updateLayout()`) |
| Default button behaviours (close/minimize/maximize actions, enabled flags, maximize checked = maximized) | `src/decorationbutton.cpp` `Private::init()` |
| Hover dispatch skips disabled buttons; title bar tested before borders for the section under the mouse | `src/decoration.cpp` `hoverMoveEvent()`, `Private::updateSectionUnderMouse()` |
| Shadow = nine-slice QImage + `innerShadowRect` + `padding`; overlap rendered behind the frame | `src/decorationshadow.h` class comment |
| `snapToPixelGrid()` / `pixelSize()` installed as `<KDecoration3/ScaleHelpers>` | `src/scalehelpers.h`, `src/CMakeLists.txt` (`ecm_generate_headers`) |
| CMake: `find_package(KDecoration3)`, target `KDecoration3::KDecoration`, private target `KDecoration3::KDecoration3Private` | `src/CMakeLists.txt` (`EXPORT_NAME KDecoration`), `src/private/CMakeLists.txt`, top `CMakeLists.txt` (`NAMESPACE KDecoration3::`) |
| `KDECMakeSettings` sets `CMAKE_SHARED_MODULE_PREFIX ""` and enables `BUILD_TESTING` | extra-cmake-modules v6.30.0 `kde-modules/KDECMakeSettings.cmake` |

## 9. Changes needed OUTSIDE this package (for the orchestrator to plan)

- `design/`: `cpp/token_colors.h` (section 2).
- `packages/kuura-shell/skel/.config/kwinrc`: `library=@NAME@.decoration`, drop `theme=`;
  its comments describe the Aurorae theme and need rewriting.
- `tests/test_shell_skel_defaults.py::test_decoration_selects_the_aurorae_qml_theme`
  asserts `library == "org.kde.kwin.aurorae"`; it must change with the requirement (tell
  the owner, per the test rules).
- Decide whether the Aurorae theme (`design/generators/aurorae.py`, its output, its tests,
  its install in kuura-shell's PKGBUILD) is retired or kept as a selectable alternative.
- docs/SHELL_CONTRACT.md "Window decoration" section: replace the Aurorae description.
