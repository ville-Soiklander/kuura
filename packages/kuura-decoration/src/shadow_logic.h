#pragma once

/**
 * @file shadow_logic.h
 * @brief Pure computation of the drop shadow: parameters, falloff profile and the
 *        nine-slice alpha image handed to KDecoration3::DecorationShadow.
 *
 * LOCKED INTERFACE (phase 1). Declarations only; the definitions go into shadow_logic.cpp.
 *
 * HOW KWIN USES THE SHADOW (kdecoration v6.7.5 src/decorationshadow.h, class comment):
 * one QImage cut into eight parts by innerShadowRect; the four corners are drawn as they
 * are, the four edges are stretched along the window side. The image is placed so that it
 * extends `padding` beyond the frame on each side; whatever lies inside the padding
 * overlaps the frame and is drawn BEHIND it. The shadow is a sibling of the window
 * container in KWin's scene (kwin src/scene/windowitem.cpp, m_shadowItem->stackBefore(
 * m_windowContainer)), so it is NOT clipped by the border radius and must carry its own
 * rounded inner cut-out.
 *
 * WHY our own renderer: Breeze draws its shadow with BoxShadowRenderer from its own
 * libbreezecommon, which is not a public library (and is GPL); we compute a small alpha
 * mask ourselves. WHY Qt-free: decoration.cpp only wraps the bytes in a QImage
 * (Format_ARGB32_Premultiplied); the profile itself is tested headless.
 *
 * THE LOOK (reproduces the QML theme, aurorae.py): the QML theme stacked
 * n = shadowSize - offsetY translucent rounded rectangles, each grown by one more pixel,
 * the stack offset offsetY = round(shadowSize / 4) downwards, with per-layer alpha
 * a = 1 - (1 - peak)^(1/n) so that all layers together reach `peak` (the alpha of
 * color.<mode>.shadow) at the window edge. shadowAlpha() is the continuous form of that
 * stack: at distance d outside the offset rectangle the covering layers number n - d, so
 * alpha(d) = 1 - (1 - peak)^((n - d) / n).
 */

#include "geometry.h"
#include "palette_logic.h"

#include <cstdint>
#include <vector>

namespace Kuura::Deco
{

/**
 * @brief Inputs of the shadow, derived from metrics and the mode palette.
 */
struct ShadowParams {
    double extent = 0.0;       ///< n: how far the shadow reaches beyond the offset frame, >= 0.
    double offsetY = 0.0;      ///< Downward offset of the shadow shape, >= 0.
    double peakAlpha = 0.0;    ///< Opacity at the frame edge, 0..1 (shadow token alpha / 255).
    double cornerRadius = 0.0; ///< Radius of the frame corners the shadow follows.
    Rgba colour;               ///< Shadow colour; its alpha is ignored here (see peakAlpha).
};

/**
 * @brief A rendered shadow mask plus the placement data for DecorationShadow.
 *
 * alpha holds width * height bytes, row-major, top row first: the final opacity 0..255 of
 * each pixel (colour applied by decoration.cpp, premultiplied there).
 */
struct ShadowImage {
    int width = 0;                    ///< Image width in pixels (logical == image pixels).
    int height = 0;                   ///< Image height in pixels.
    std::vector<std::uint8_t> alpha;  ///< width * height opacity values.
    RectF innerShadowRect;            ///< For DecorationShadow::setInnerShadowRect().
    MarginsF padding;                 ///< For DecorationShadow::setPadding().
    Rgba colour;                      ///< Copied from ShadowParams::colour.
};

/**
 * @brief Derive the shadow parameters.
 *
 * offsetY = std::round(m.shadowSize / 4) (half away from zero, which equals QML
 * Math.round for these non-negative values: 2 -> 1, 6 -> 2, 16 -> 4);
 * extent = max(0, m.shadowSize - offsetY);
 * peakAlpha = palette.shadow.a / 255; cornerRadius = m.cornerRadius;
 * colour = palette.shadow.
 *
 * @param m Valid metrics.
 * @param palette Palette of the current mode (the shadow differs per mode: light 0x33,
 *        dark 0x66 alpha in the shipped tokens).
 * @return Parameters; extent == 0 means "no shadow".
 */
ShadowParams shadowParams(const Metrics &m, const ModePalette &palette);

/**
 * @brief How far the shadow image extends beyond the frame on each side.
 *
 * {extent, max(0, extent - offsetY), extent, extent + offsetY}: the shape is moved down by
 * offsetY, so it reaches less far above the window and further below it.
 *
 * @param p Shadow parameters.
 * @return Padding for DecorationShadow::setPadding().
 */
MarginsF shadowPadding(const ShadowParams &p);

/**
 * @brief Shadow opacity at a signed distance from the OFFSET frame shape.
 *
 * distance <= 0 -> peakAlpha; 0 < distance < extent -> 1 - (1 - peakAlpha)^((extent -
 * distance) / extent); distance >= extent -> 0. extent <= 0 -> 0 everywhere.
 * Monotonically non-increasing in distance.
 *
 * @param distance Signed distance in logical pixels (negative = inside the shape).
 * @param p Shadow parameters.
 * @return Opacity 0..1.
 */
double shadowAlpha(double distance, const ShadowParams &p);

/**
 * @brief Signed distance from a point to a rounded rectangle.
 *
 * Negative inside, 0 on the outline, positive outside; the corner radius is clamped to
 * [0, min(width, height) / 2]. Standard rounded-box distance (Euclidean distance to the
 * rectangle shrunk by the radius, minus the radius).
 *
 * @param p Point.
 * @param rect Rectangle (must not be empty).
 * @param radius Corner radius.
 * @return Distance in the same units as the inputs.
 */
double roundedRectSignedDistance(const PointF &p, const RectF &rect, double radius);

/**
 * @brief Render the nine-slice shadow mask.
 *
 * Layout: a "core" box of side 2 * c + 1 with c = ceil(cornerRadius) + ceil(offsetY) + 1
 * stands for the frame; the image is the core plus padding (shadowPadding()) on each side.
 * For the pixel centre q = (x + 0.5, y + 0.5):
 *   shape   = core box moved down by offsetY, corner radius cornerRadius;
 *   value   = shadowAlpha(roundedRectSignedDistance(q, shape, cornerRadius), p);
 *   cut-out = clamp(roundedRectSignedDistance(q, core, cornerRadius) + 0.5, 0, 1)
 *             (0 inside the frame, antialiased over one pixel at its edge);
 *   alpha   = round(255 * value * cut-out).
 * innerShadowRect = {padding.left + c, padding.top + c, 1, 1}.
 *
 * WHY c includes the offset: the edge rows/columns that KWin stretches must lie on the
 * STRAIGHT part of both the shape and the cut-out, otherwise stretching would smear a
 * corner along the side. WHY the cut-out: a translucent client (or the transparent
 * corner outside the rounded frame) must not show the shadow through it; Breeze does the
 * same (DestinationOut of the inner rounded rect in createShadowObject()).
 *
 * @param p Shadow parameters.
 * @return The mask; width == height == 0 and empty alpha if p.extent <= 0 or
 *         p.peakAlpha <= 0 (decoration.cpp then calls setShadow(nullptr)).
 */
ShadowImage renderShadowImage(const ShadowParams &p);

} // namespace Kuura::Deco
