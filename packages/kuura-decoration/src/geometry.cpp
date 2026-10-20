// Implementation of geometry.h: the Qt-free layout rules of the window decoration.
// Every public function is documented in geometry.h; comments here explain only the
// non-obvious arithmetic.

#include "geometry.h"

#include <tokens.h>

#include <algorithm>
#include <cmath>

namespace Kuura::Deco
{

namespace
{

/// True if @p v is finite and lies in the closed range [lo, hi].
bool inRange(double v, double lo, double hi)
{
    return std::isfinite(v) && v >= lo && v <= hi;
}

/// A scale that is not a usable multiplier (NaN, inf, 0 or negative) means "no scaling".
/// WHY: DecoratedWindow::nextScale() is 1 until KWin knows the output; a broken value must
/// never turn a border into NaN or zero.
double sanitizeScale(double scale)
{
    return (std::isfinite(scale) && scale > 0.0) ? scale : 1.0;
}

/// Maps a design-grid point (0..kGlyphGrid) onto the disc rectangle.
PointF mapGridPoint(const PointF &p, const RectF &disc)
{
    return PointF{disc.x + p.x * disc.width / kGlyphGrid, disc.y + p.y * disc.height / kGlyphGrid};
}

} // namespace

Metrics tokenMetrics()
{
    // The token constants have mixed types (int and float); everything is widened to
    // double once here so the layout code never mixes types.
    Metrics m;
    m.titleBarHeight = static_cast<double>(Kuura::Tokens::kDecorationTitlebarHeight);
    m.buttonDiameter = static_cast<double>(Kuura::Tokens::kDecorationButtonDiameter);
    m.buttonSpacing = static_cast<double>(Kuura::Tokens::kDecorationButtonSpacing);
    m.buttonInset = static_cast<double>(Kuura::Tokens::kDecorationButtonInset);
    m.glyphStroke = static_cast<double>(Kuura::Tokens::kDecorationGlyphStroke);
    m.shadowSize = static_cast<double>(Kuura::Tokens::kDecorationShadowSize);
    m.cornerRadius = static_cast<double>(Kuura::Tokens::kRadiusWindow);
    m.hairline = static_cast<double>(Kuura::Tokens::kStrokeHairline);
    m.captionGap = static_cast<double>(Kuura::Tokens::kSpacingGutter);
    return m;
}

bool isValid(const Metrics &m)
{
    // Ranges mirror design/validate.py; the last two clauses are layout invariants that
    // validate.py does not need to know about (discs and corners must fit in the bar).
    return inRange(m.titleBarHeight, 24.0, 64.0)
        && inRange(m.buttonDiameter, 8.0, 20.0)
        && inRange(m.buttonSpacing, 0.0, 24.0)
        && inRange(m.buttonInset, 0.0, 32.0)
        && inRange(m.glyphStroke, 0.5, 3.0)
        && inRange(m.shadowSize, 0.0, 32.0)
        && std::isfinite(m.cornerRadius) && m.cornerRadius >= 0.0 && m.cornerRadius <= m.titleBarHeight
        && std::isfinite(m.hairline) && m.hairline > 0.0
        && std::isfinite(m.captionGap) && m.captionGap >= 0.0
        && m.buttonDiameter <= m.titleBarHeight;
}

bool isEmpty(const RectF &r)
{
    return r.width <= 0.0 || r.height <= 0.0;
}

bool contains(const RectF &r, const PointF &p)
{
    // Half-open on the right/bottom so two adjacent rectangles never both claim a point.
    return !isEmpty(r) && p.x >= r.x && p.x < r.x + r.width && p.y >= r.y && p.y < r.y + r.height;
}

MarginsF frameBorders(const Metrics &m, BorderPreset preset, bool maximized)
{
    MarginsF b;
    b.top = m.titleBarHeight;
    if (maximized) {
        return b;
    }
    switch (preset) {
    case BorderPreset::Normal:
        b.left = b.right = b.bottom = kNormalBorder;
        break;
    case BorderPreset::NoSides:
        // "No side borders" keeps a hairline-thin side but a full bottom edge to grab.
        b.left = b.right = kThinBorder;
        b.bottom = kNormalBorder;
        break;
    case BorderPreset::None:
        b.left = b.right = b.bottom = kThinBorder;
        break;
    }
    return b;
}

MarginsF resizeOnlyBorders(BorderPreset preset, bool maximizedHorizontally, bool maximizedVertically)
{
    MarginsF r;
    switch (preset) {
    case BorderPreset::Normal:
        break;
    case BorderPreset::NoSides:
        r.left = r.right = kResizeOnlyBorder;
        break;
    case BorderPreset::None:
        r.left = r.right = r.bottom = kResizeOnlyBorder;
        break;
    }
    // An edge that cannot be dragged (its direction is maximized) gets no grab area.
    if (maximizedHorizontally) {
        r.left = r.right = 0.0;
    }
    if (maximizedVertically) {
        r.bottom = 0.0;
    }
    return r;
}

RectF titleBarRect(const Metrics &m, double decorationWidth, const MarginsF &borders, bool maximized)
{
    if (maximized) {
        return RectF{0.0, 0.0, std::max(0.0, decorationWidth), m.titleBarHeight};
    }
    // Inset from the top by kTopResizeStrip and from the sides by the borders, so the
    // framework still finds the top edge and the two top corners as resize sections.
    const double width = std::max(0.0, decorationWidth - borders.left - borders.right);
    return RectF{borders.left, kTopResizeStrip, width, m.titleBarHeight - kTopResizeStrip};
}

double buttonGroupWidth(std::size_t count, const Metrics &m)
{
    if (count == 0) {
        return 0.0;
    }
    const auto n = static_cast<double>(count);
    return n * m.buttonDiameter + (n - 1.0) * m.buttonSpacing;
}

PointF buttonGroupOrigin(GroupSide side, double decorationWidth, double groupWidth, const Metrics &m)
{
    // floor() reproduces the QML theme's integer centring: with an odd difference the
    // extra pixel goes below the discs, never above.
    const double y = std::floor((m.titleBarHeight - m.buttonDiameter) / 2.0);
    const double x = (side == GroupSide::Left) ? m.buttonInset : decorationWidth - m.buttonInset - groupWidth;
    return PointF{x, y};
}

std::vector<RectF> buttonRects(std::size_t count, const PointF &origin, const Metrics &m)
{
    std::vector<RectF> rects;
    rects.reserve(count);
    const double step = m.buttonDiameter + m.buttonSpacing;
    for (std::size_t i = 0; i < count; ++i) {
        rects.push_back(RectF{origin.x + static_cast<double>(i) * step, origin.y, m.buttonDiameter, m.buttonDiameter});
    }
    return rects;
}

RectF hoverZone(const RectF &group, const Metrics &m)
{
    if (isEmpty(group)) {
        return RectF{};
    }
    // Full bar height on purpose: the pointer moving vertically past a disc must not
    // flicker the glyphs off while it is still "at the buttons".
    return RectF{group.x - kHoverSlack, 0.0, group.width + 2.0 * kHoverSlack, m.titleBarHeight};
}

RectF captionRect(double decorationWidth, double leftGroupWidth, double rightGroupWidth, const Metrics &m)
{
    // The same padding on both sides keeps the caption centred in the whole bar even
    // when only one side has buttons.
    const double pad = m.buttonInset + std::max(leftGroupWidth, rightGroupWidth) + m.captionGap;
    return RectF{pad, 0.0, std::max(0.0, decorationWidth - 2.0 * pad), m.titleBarHeight};
}

double cornerRadius(const Metrics &m, bool maximized)
{
    return maximized ? 0.0 : m.cornerRadius;
}

double snapToPixelGrid(double value, double scale)
{
    const double s = sanitizeScale(scale);
    return std::round(value * s) / s;
}

double outlineThickness(const Metrics &m, double scale)
{
    // Never thinner than one device pixel, otherwise a fractional scale could round the
    // hairline away entirely.
    const double s = sanitizeScale(scale);
    return std::max(1.0 / s, snapToPixelGrid(m.hairline, s));
}

std::vector<GlyphBar> glyphBars(Glyph glyph, const RectF &disc, double stroke)
{
    const PointF centre{disc.x + disc.width / 2.0, disc.y + disc.height / 2.0};
    switch (glyph) {
    case Glyph::Close: {
        // "+ stroke" compensates for the round caps so the visible cross matches the
        // QML theme, whose bars were measured including their caps.
        const double length = kCloseBarFactor * disc.width + stroke;
        return {GlyphBar{centre, length, stroke, 45.0}, GlyphBar{centre, length, stroke, -45.0}};
    }
    case Glyph::Minimize:
        return {GlyphBar{centre, kMinimizeBarFactor * disc.width + stroke, stroke, 0.0}};
    case Glyph::None:
    case Glyph::Maximize:
    case Glyph::Restore:
        break;
    }
    return {};
}

std::vector<GridTriangle> glyphTriangles(Glyph glyph, const RectF &disc)
{
    const std::array<GridTriangle, 2> *source = nullptr;
    if (glyph == Glyph::Maximize) {
        source = &kMaximizeTriangles;
    } else if (glyph == Glyph::Restore) {
        source = &kRestoreTriangles;
    } else {
        return {};
    }
    std::vector<GridTriangle> out;
    out.reserve(source->size());
    for (const GridTriangle &t : *source) {
        out.push_back(GridTriangle{mapGridPoint(t[0], disc), mapGridPoint(t[1], disc), mapGridPoint(t[2], disc)});
    }
    return out;
}

} // namespace Kuura::Deco
