#pragma once

/**
 * @file geometry.h
 * @brief Pure layout logic of the window decoration: borders, title bar, button discs,
 *        caption area, corner radius and hover-glyph shapes.
 *
 * LOCKED INTERFACE (phase 1). Declarations only; the definitions go into geometry.cpp.
 *
 * WHY a separate, Qt-free header: everything here is arithmetic on numbers that come from
 * the design tokens. Keeping it free of Qt and KDecoration3 lets the unit tests compile and
 * run in the package build container without a compositor, a display or a Qt event loop,
 * and lets them check the layout rules at the token limits (design/validate.py ranges)
 * instead of only at today's token values. decoration.cpp converts these plain structs to
 * QRectF / QMarginsF and hands them to KDecoration3.
 *
 * COORDINATES: every rectangle is in KDecoration3 "decoration coordinates", i.e. logical
 * pixels with the origin at the top-left corner of the decoration frame (the frame
 * includes the borders and the title bar, but NOT the shadow, which KWin draws from a
 * separate DecorationShadow outside the frame; kdecoration v6.7.5 src/decorationshadow.h,
 * class comment). Decoration::setTitleBar() documents its argument as "geometry of the
 * titleBar in Decoration coordinates" (kdecoration src/decoration.h, setTitleBar()).
 *
 * VISUAL SPEC: reproduces the Aurorae QML theme rendered by design/generators/aurorae.py
 * (docs/SHELL_CONTRACT.md, "Window decoration"), which this plugin replaces. Every
 * deliberate difference from that theme is marked "DEVIATION" below.
 */

#include <array>
#include <cstddef>
#include <vector>

namespace Kuura::Deco
{

/**
 * @brief A point in logical pixels.
 */
struct PointF {
    double x = 0.0; ///< Horizontal position, grows to the right.
    double y = 0.0; ///< Vertical position, grows downwards.
};

/**
 * @brief An axis-aligned rectangle in logical pixels.
 *
 * A rectangle with width <= 0 or height <= 0 is "empty" (see isEmpty()).
 */
struct RectF {
    double x = 0.0;      ///< Left edge.
    double y = 0.0;      ///< Top edge.
    double width = 0.0;  ///< Width; never negative in values returned by this header.
    double height = 0.0; ///< Height; never negative in values returned by this header.
};

/**
 * @brief Four edge widths in logical pixels (same order as QMarginsF's constructor).
 */
struct MarginsF {
    double left = 0.0;
    double top = 0.0;
    double right = 0.0;
    double bottom = 0.0;
};

/**
 * @brief Border-size choice reduced to the three cases the design distinguishes.
 *
 * WHY only three: KDecoration3::BorderSize has nine values (None, NoSides, Tiny, Normal,
 * Large, VeryLarge, Huge, VeryHuge, Oversized; kdecoration src/decorationdefines.h), but the
 * spec, like the bundled Plastik theme the QML theme followed, only distinguishes "no
 * borders", "no side borders" and "everything else" (docs/SHELL_CONTRACT.md, "Border
 * size"). The mapping from KDecoration3::BorderSize lives in decoration.h
 * (borderPresetFor()) so this header stays Qt-free.
 */
enum class BorderPreset {
    None,    ///< KDecoration3::BorderSize::None.
    NoSides, ///< KDecoration3::BorderSize::NoSides.
    Normal,  ///< Every other KDecoration3::BorderSize value.
};

/**
 * @brief The title-bar buttons this decoration draws.
 *
 * WHY no other types: the project's button layout is close, minimize, maximize
 * (skel kwinrc `ButtonsOnLeft=XIA`); a Spacer is kept so a user layout containing "_"
 * still spaces correctly. Every other KDecoration3::DecorationButtonType is not created
 * at all (see Button::create() in button.h).
 */
enum class ButtonKind {
    Close,
    Minimize,
    Maximize, ///< Also shows the restore glyph while the window is maximized.
    Spacer,   ///< Empty slot of one disc diameter; never painted.
};

/**
 * @brief Which of the two button groups a layout question is about.
 */
enum class GroupSide {
    Left,
    Right,
};

/**
 * @brief The glyph drawn on a disc while the glyphs are shown.
 */
enum class Glyph {
    None,     ///< No glyph (not hovered, or a Spacer).
    Close,    ///< Two crossed bars.
    Minimize, ///< One horizontal bar.
    Maximize, ///< Two filled triangles pointing at the outer corners.
    Restore,  ///< The same two triangles turned inwards (maximized window).
};

/**
 * @brief The token-derived sizes the layout depends on, in logical pixels.
 *
 * WHY a struct instead of reading Kuura::Tokens constants inside each function: the unit
 * tests must be able to feed limit values (e.g. titlebar_height 24 and 64) that differ from
 * the shipped tokens. Production code gets the shipped values from tokenMetrics().
 */
struct Metrics {
    double titleBarHeight = 0.0; ///< decoration.titlebar_height (24..64).
    double buttonDiameter = 0.0; ///< decoration.button_diameter (8..20).
    double buttonSpacing = 0.0;  ///< decoration.button_spacing (0..24), gap between discs.
    double buttonInset = 0.0;    ///< decoration.button_inset (0..32), frame edge to first disc.
    double glyphStroke = 0.0;    ///< decoration.glyph_stroke (0.5..3), glyph bar thickness.
    double shadowSize = 0.0;     ///< decoration.shadow_size (0..32), 0 = no shadow.
    double cornerRadius = 0.0;   ///< radius.window, must not exceed titleBarHeight.
    double hairline = 0.0;       ///< stroke.hairline, width of the frame outline.
    double captionGap = 0.0;     ///< spacing.gutter, gap between buttons and caption.
};

// ---- Design constants that are NOT tokens --------------------------------------------
// WHY constants here and not tokens: they are the fixed values of the QML theme
// (design/generators/aurorae.py); none of them is a design-system value in tokens.json.
// If the owner wants any of them tunable, it becomes a token and moves to Metrics.

/// Side and bottom border for the "Normal" preset; the minimum KWin honours for the default
/// border size (aurorae.py `_BORDER`).
inline constexpr double kNormalBorder = 4.0;
/// Visible border for the "None" / "NoSides" presets (QML theme `borders.setBorders(1)`).
inline constexpr double kThinBorder = 1.0;
/// Invisible extra grab area for the thin presets (QML theme `extendedBorders` = 3).
inline constexpr double kResizeOnlyBorder = 3.0;
/// Height of the strip at the top of a floating window that resizes instead of moving it.
/// DEVIATION from the QML theme (which used y = 0): Decoration::Private::
/// updateSectionUnderMouse() (kdecoration src/decoration.cpp) tests the title bar rect
/// BEFORE the top border, so a title bar starting at y = 0 makes the top edge impossible to
/// resize. Breeze avoids this the same way (breeze kdecoration/breezedecoration.cpp,
/// Decoration::updateTitleBar(), top margin). Equal to kNormalBorder so all four edges
/// have the same grab width.
inline constexpr double kTopResizeStrip = 4.0;
/// Horizontal slack around a button group that still counts as "over the buttons", so the
/// glyphs stay visible while the pointer crosses the gaps (QML theme hover MouseAreas,
/// `x: group.x - 4`, `width: group.width + 8`).
inline constexpr double kHoverSlack = 4.0;
/// Close glyph bar length = kCloseBarFactor * diameter + stroke (QML `size * 0.42 + stroke`).
inline constexpr double kCloseBarFactor = 0.42;
/// Minimize glyph bar length = kMinimizeBarFactor * diameter + stroke (QML `size * 0.35`).
inline constexpr double kMinimizeBarFactor = 0.35;
/// Side of the design grid the triangle glyphs are defined on; scaled to the diameter.
inline constexpr double kGlyphGrid = 12.0;

/**
 * @brief A filled triangle on the kGlyphGrid x kGlyphGrid design grid.
 */
using GridTriangle = std::array<PointF, 3>;

/// Maximize glyph: two triangles pointing at the top-right and bottom-left corners
/// (aurorae.py `_MAXIMIZE_TRIANGLES`, values copied from the design, not from any library).
inline constexpr std::array<GridTriangle, 2> kMaximizeTriangles{{
    {{{8.6, 3.4}, {8.6, 7.1}, {4.9, 3.4}}},
    {{{3.4, 8.6}, {3.4, 4.9}, {7.1, 8.6}}},
}};
/// Restore glyph: the same pair turned inwards (aurorae.py `_RESTORE_TRIANGLES`).
inline constexpr std::array<GridTriangle, 2> kRestoreTriangles{{
    {{{7.3, 2.7}, {7.3, 4.7}, {5.3, 4.7}}},
    {{{4.7, 9.3}, {4.7, 7.3}, {6.7, 7.3}}},
}};

/**
 * @brief A rounded bar of a glyph (rectangle with fully rounded ends), possibly rotated.
 */
struct GlyphBar {
    PointF centre;          ///< Centre of the bar, in decoration coordinates.
    double length = 0.0;    ///< Extent along the bar's axis.
    double thickness = 0.0; ///< Extent across the axis; the end caps have radius thickness/2.
    double angleDegrees = 0.0; ///< Clockwise rotation around centre (Qt's convention).
};

// ---- Functions -----------------------------------------------------------------------

/**
 * @brief Build the metrics from the generated token header.
 *
 * Reads Kuura::Tokens::kDecorationTitlebarHeight, kDecorationButtonDiameter,
 * kDecorationButtonSpacing, kDecorationButtonInset, kDecorationGlyphStroke,
 * kDecorationShadowSize, kRadiusWindow, kStrokeHairline and kSpacingGutter from
 * <tokens.h> (design/generators/cpp_header.py; all are already emitted because that
 * generator exports every non-colour leaf). Only geometry.cpp includes <tokens.h>.
 *
 * WHY: tokens.json is the single source of truth; no token value is ever written as a
 * literal in this package.
 *
 * @return The shipped metrics. Never fails (values are compile-time constants).
 */
Metrics tokenMetrics();

/**
 * @brief Check that metrics are inside the ranges design/validate.py enforces.
 *
 * Ranges: titleBarHeight 24..64, buttonDiameter 8..20, buttonSpacing 0..24,
 * buttonInset 0..32, glyphStroke 0.5..3, shadowSize 0..32, cornerRadius >= 0 and
 * <= titleBarHeight, hairline > 0, captionGap >= 0; every value finite. Additionally the
 * discs must fit vertically: buttonDiameter <= titleBarHeight.
 *
 * WHY here too: the generator already validates, but Metrics can also be built by hand
 * (tests, a future config page). The layout functions assume valid metrics; decoration.cpp
 * asserts this once in init() and falls back to tokenMetrics() if it ever fails.
 *
 * @param m Metrics to check.
 * @return true if every value is in range.
 */
bool isValid(const Metrics &m);

/**
 * @brief True if the rectangle has no area.
 * @param r Rectangle to test.
 * @return true if r.width <= 0 or r.height <= 0.
 */
bool isEmpty(const RectF &r);

/**
 * @brief Half-open containment test, the same rule as QRectF::contains for non-empty rects.
 * @param r Rectangle.
 * @param p Point.
 * @return true if r is not empty and r.x <= p.x < r.x + r.width and r.y <= p.y < r.y + r.height.
 */
bool contains(const RectF &r, const PointF &p);

/**
 * @brief Decoration borders (the frame around the client) for Decoration::setBorders().
 *
 * Result: top is always m.titleBarHeight (the title bar replaces the top border).
 * Maximized: left = right = bottom = 0. Otherwise by preset:
 * Normal -> kNormalBorder on left, right and bottom; NoSides -> kThinBorder on left and
 * right, kNormalBorder at the bottom; None -> kThinBorder on left, right and bottom.
 *
 * WHY: matches the QML theme's applyBorders() (aurorae.py). The values are logical pixels;
 * decoration.cpp snaps them with snapToPixelGrid() at the window's nextScale(), as Breeze
 * does in Decoration::bordersFor() / recalculateBorders(), so fractional scaling does not
 * produce half-pixel seams.
 *
 * @param m Valid metrics.
 * @param preset Border preset of the current settings.
 * @param maximized True if the window is maximized in both directions.
 * @return Border widths, all >= 0.
 */
MarginsF frameBorders(const Metrics &m, BorderPreset preset, bool maximized);

/**
 * @brief Invisible resize-only borders for Decoration::setResizeOnlyBorders().
 *
 * None -> kResizeOnlyBorder on left, right and bottom; NoSides -> kResizeOnlyBorder on left
 * and right; Normal -> all 0. Top is always 0 (the title bar strip handles the top edge,
 * see kTopResizeStrip). A side whose direction is maximized gets 0 (Breeze does the same
 * in recalculateBorders(): no grab area on an edge that cannot be resized).
 *
 * WHY: setResizeOnlyBorders() adds input area outside the visible frame
 * (kwin src/window.cpp, Window::updateDecorationInputShape(): outerRect = inner + borders +
 * resizeOnlyBorders), which keeps thin borders resizable.
 *
 * @param preset Border preset.
 * @param maximizedHorizontally Window fills the screen width.
 * @param maximizedVertically Window fills the screen height.
 * @return Resize-only margins, all >= 0.
 */
MarginsF resizeOnlyBorders(BorderPreset preset, bool maximizedHorizontally, bool maximizedVertically);

/**
 * @brief Rectangle passed to Decoration::setTitleBar(): the area that moves the window and
 *        maximizes on double click.
 *
 * Maximized: {0, 0, decorationWidth, m.titleBarHeight}. Otherwise
 * {borders.left, kTopResizeStrip, decorationWidth - borders.left - borders.right,
 *  m.titleBarHeight - kTopResizeStrip} (see kTopResizeStrip for the DEVIATION).
 *
 * WHY x = borders.left: the left and right border columns next to the title bar must stay
 * resize corners; updateSectionUnderMouse() only reports a corner when the pointer is not
 * inside the title bar rect (kdecoration src/decoration.cpp).
 *
 * @param m Valid metrics.
 * @param decorationWidth Full frame width (client width + left + right border), >= 0.
 * @param borders Result of frameBorders() for the same state.
 * @param maximized True if the window is maximized.
 * @return Title bar rect; width clamped to >= 0.
 */
RectF titleBarRect(const Metrics &m, double decorationWidth, const MarginsF &borders, bool maximized);

/**
 * @brief Width of a button group holding @p count buttons.
 *
 * count * buttonDiameter + (count - 1) * buttonSpacing, or 0 for count == 0.
 *
 * WHY: identical to DecorationButtonGroup::Private::updateLayout() (kdecoration
 * src/decorationbuttongroup.cpp) for a group whose buttons are all visible. This plugin
 * never hides a created button (a disabled one is dimmed, see palette_logic.h), so the
 * formula holds; NOTE that updateLayout() adds a trailing spacing when the LAST button is
 * invisible, which is one more reason not to hide buttons. At run time decoration.cpp
 * reads the real DecorationButtonGroup::geometry() rather than this value; this function
 * exists so the layout can be tested.
 *
 * @param count Number of buttons (Spacers included).
 * @param m Valid metrics.
 * @return Width in logical pixels, >= 0.
 */
double buttonGroupWidth(std::size_t count, const Metrics &m);

/**
 * @brief Top-left position for DecorationButtonGroup::setPos().
 *
 * Left: x = m.buttonInset. Right: x = decorationWidth - m.buttonInset - groupWidth.
 * Both: y = floor((m.titleBarHeight - m.buttonDiameter) / 2), i.e. the discs are centred
 * in the whole bar, with the QML theme's rounding.
 *
 * WHY measured from the outer frame edge, not from the border: the QML theme placed the
 * group at `sideInset` inside the frame item, which starts at the outer edge.
 *
 * @param side Which group.
 * @param decorationWidth Full frame width.
 * @param groupWidth Width of that group (buttonGroupWidth() or the live group geometry).
 * @param m Valid metrics.
 * @return Group origin in decoration coordinates.
 */
PointF buttonGroupOrigin(GroupSide side, double decorationWidth, double groupWidth, const Metrics &m);

/**
 * @brief Disc rectangles of a group, left to right, as DecorationButtonGroup lays them out
 *        in a left-to-right session.
 *
 * Button i: {origin.x + i * (diameter + spacing), origin.y, diameter, diameter}.
 *
 * WHY the button geometry equals the disc: the QML theme's hit area was exactly the disc.
 * Each Button gets setGeometry({0, 0, diameter, diameter}) and the group positions it
 * (Breeze does the same split: Decoration::updateButtonsGeometry() sets sizes, the group
 * sets positions). Right-to-left layouts are mirrored by DecorationButtonGroup itself.
 *
 * @param count Number of buttons.
 * @param origin Group origin (buttonGroupOrigin()).
 * @param m Valid metrics.
 * @return count rectangles (empty vector for count == 0).
 */
std::vector<RectF> buttonRects(std::size_t count, const PointF &origin, const Metrics &m);

/**
 * @brief Area in which the pointer makes the glyphs of ALL buttons appear.
 *
 * {group.x - kHoverSlack, 0, group.width + 2 * kHoverSlack, m.titleBarHeight}; an empty
 * rect if @p group is empty.
 *
 * WHY: the spec shows the glyphs on all three discs while the pointer is over any of them
 * or in the gaps between them. KDecoration3 only tracks hover per button
 * (DecorationButton::isHovered()), and Decoration::hoverMoveEvent() skips disabled
 * buttons (kdecoration src/decoration.cpp), so the decoration tests this zone itself in
 * its hoverMoveEvent() override.
 *
 * @param group Live geometry of one button group.
 * @param m Valid metrics.
 * @return Hover zone in decoration coordinates.
 */
RectF hoverZone(const RectF &group, const Metrics &m);

/**
 * @brief Rectangle the caption text is drawn in (centred, elided in the middle).
 *
 * pad = m.buttonInset + max(leftGroupWidth, rightGroupWidth) + m.captionGap;
 * result {pad, 0, max(0, decorationWidth - 2 * pad), m.titleBarHeight}.
 *
 * WHY symmetric padding: the caption is centred in the WHOLE bar, not in the space left by
 * the buttons (spec, "the caption is centred in the whole bar").
 *
 * @param decorationWidth Full frame width.
 * @param leftGroupWidth Width of the left group (0 if empty).
 * @param rightGroupWidth Width of the right group (0 if empty).
 * @param m Valid metrics.
 * @return Caption rect; may have width 0 on a very narrow window.
 */
RectF captionRect(double decorationWidth, double leftGroupWidth, double rightGroupWidth, const Metrics &m);

/**
 * @brief Corner radius for all four corners, for Decoration::setBorderRadius() and
 *        setBorderOutline().
 *
 * 0 when maximized, otherwise m.cornerRadius.
 *
 * WHY all four corners: KWin clips the whole window container (decoration AND client
 * surface) to the frame rect with this radius (kwin src/scene/windowitem.cpp,
 * WindowItem::updateBorderRadius() -> m_windowContainer->setBorderRadius();
 * src/scene/itemrenderer_opengl.cpp pushes it on the corner stack for all child items).
 * That is exactly what the QML theme could not do: round the BOTTOM corners including the
 * client content. Breeze passes 0 for corners it draws itself; we let KWin clip all four.
 *
 * @param m Valid metrics.
 * @param maximized True if maximized.
 * @return Radius in logical pixels, >= 0.
 */
double cornerRadius(const Metrics &m, bool maximized);

/**
 * @brief Round a logical length to the device pixel grid.
 *
 * round(value * scale) / scale; a scale that is not finite or <= 0 is treated as 1.
 *
 * WHY a copy: identical formula to KDecoration3::snapToPixelGrid() (kdecoration
 * src/scalehelpers.h, installed as <KDecoration3/ScaleHelpers>), duplicated so this
 * header stays Qt-free. decoration.cpp may call either; tests compare both.
 *
 * @param value Length in logical pixels.
 * @param scale Device pixels per logical pixel (DecoratedWindow::nextScale()).
 * @return Snapped length.
 */
double snapToPixelGrid(double value, double scale);

/**
 * @brief Thickness of the frame outline (BorderOutline) at a given scale.
 *
 * max(1 / scale, snapToPixelGrid(m.hairline, scale)), scale sanitised as above.
 *
 * WHY: the same rule Breeze uses for its outline (recalculateBorders(): max(pixelSize,
 * snapToPixelGrid(1))), so the hairline never vanishes below one device pixel.
 *
 * @param m Valid metrics.
 * @param scale Device pixels per logical pixel.
 * @return Thickness in logical pixels, > 0.
 */
double outlineThickness(const Metrics &m, double scale);

/**
 * @brief Bars that make up a glyph, centred on @p disc.
 *
 * Close: two bars of length kCloseBarFactor * disc.width + stroke, thickness stroke, at
 * +45 and -45 degrees. Minimize: one bar of length kMinimizeBarFactor * disc.width + stroke
 * at 0 degrees. Every other glyph: no bars.
 *
 * @param glyph Glyph to draw.
 * @param disc Disc rectangle (square).
 * @param stroke m.glyphStroke.
 * @return 0, 1 or 2 bars.
 */
std::vector<GlyphBar> glyphBars(Glyph glyph, const RectF &disc, double stroke);

/**
 * @brief Filled triangles that make up a glyph, scaled from the design grid to @p disc.
 *
 * Maximize: kMaximizeTriangles, Restore: kRestoreTriangles, each point mapped as
 * disc.x + p.x * disc.width / kGlyphGrid (and the same for y). Every other glyph: none.
 *
 * @param glyph Glyph to draw.
 * @param disc Disc rectangle (square).
 * @return 0 or 2 triangles in decoration coordinates.
 */
std::vector<GridTriangle> glyphTriangles(Glyph glyph, const RectF &disc);

} // namespace Kuura::Deco
