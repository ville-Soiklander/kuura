// Implementation of shadow_logic.h: shadow parameters, the falloff profile and the
// nine-slice alpha mask. Every public function is documented in the header; comments
// here explain only the non-obvious geometry.

#include "shadow_logic.h"

#include <algorithm>
#include <cmath>

namespace Kuura::Deco
{

ShadowParams shadowParams(const Metrics &m, const ModePalette &palette)
{
    ShadowParams p;
    // std::round is half away from zero, equal to the QML theme's Math.round for the
    // non-negative shadow sizes the tokens allow.
    p.offsetY = std::round(m.shadowSize / 4.0);
    p.extent = std::max(0.0, m.shadowSize - p.offsetY);
    p.peakAlpha = palette.shadow.a / 255.0;
    p.cornerRadius = m.cornerRadius;
    p.colour = palette.shadow;
    return p;
}

MarginsF shadowPadding(const ShadowParams &p)
{
    // The shape is moved down by offsetY: it reaches offsetY less far above the frame
    // and offsetY further below it.
    return MarginsF{.left = p.extent,
                    .top = std::max(0.0, p.extent - p.offsetY),
                    .right = p.extent,
                    .bottom = p.extent + p.offsetY};
}

double shadowAlpha(double distance, const ShadowParams &p)
{
    if (!(p.extent > 0.0)) {
        return 0.0;
    }
    if (distance <= 0.0) {
        return p.peakAlpha;
    }
    if (distance >= p.extent) {
        return 0.0;
    }
    // Continuous form of the QML theme's stack of n = extent translucent layers: at
    // distance d, (n - d) layers of alpha 1 - (1 - peak)^(1/n) overlap.
    return 1.0 - std::pow(1.0 - p.peakAlpha, (p.extent - distance) / p.extent);
}

double roundedRectSignedDistance(const PointF &p, const RectF &rect, double radius)
{
    const double halfW = rect.width / 2.0;
    const double halfH = rect.height / 2.0;
    const double r = std::clamp(radius, 0.0, std::min(halfW, halfH));
    // Work in the first quadrant around the centre (the box is symmetric), against the
    // box shrunk by the radius: outside distance is Euclidean to its corner region,
    // inside distance is the (negative) distance to the nearest side.
    const double qx = std::fabs(p.x - (rect.x + halfW)) - (halfW - r);
    const double qy = std::fabs(p.y - (rect.y + halfH)) - (halfH - r);
    const double outside = std::hypot(std::max(qx, 0.0), std::max(qy, 0.0));
    const double inside = std::min(std::max(qx, qy), 0.0);
    return outside + inside - r;
}

ShadowImage renderShadowImage(const ShadowParams &p)
{
    ShadowImage img;
    img.colour = p.colour;
    if (!(p.extent > 0.0) || !(p.peakAlpha > 0.0)) {
        return img;
    }

    const MarginsF pad = shadowPadding(p);
    // The core must be large enough that its centre row/column lies on the straight part
    // of both the offset shape (radius + offset) and the cut-out; see the header's WHY.
    const double c = std::ceil(p.cornerRadius) + std::ceil(p.offsetY) + 1.0;
    const double coreSide = 2.0 * c + 1.0;

    // Padding values are whole numbers for the token ranges (shadowSize is an integer
    // token); lround makes any fractional input deterministic rather than truncated.
    const long padL = std::lround(pad.left);
    const long padT = std::lround(pad.top);
    const long padR = std::lround(pad.right);
    const long padB = std::lround(pad.bottom);
    const long core = std::lround(coreSide);

    img.width = static_cast<int>(padL + core + padR);
    img.height = static_cast<int>(padT + core + padB);
    img.alpha.assign(static_cast<std::size_t>(img.width) * static_cast<std::size_t>(img.height), 0);
    img.padding = MarginsF{.left = static_cast<double>(padL),
                           .top = static_cast<double>(padT),
                           .right = static_cast<double>(padR),
                           .bottom = static_cast<double>(padB)};
    img.innerShadowRect =
        RectF{.x = static_cast<double>(padL) + c, .y = static_cast<double>(padT) + c, .width = 1.0, .height = 1.0};

    const RectF coreRect{
        .x = static_cast<double>(padL), .y = static_cast<double>(padT), .width = coreSide, .height = coreSide};
    const RectF shape{.x = coreRect.x, .y = coreRect.y + p.offsetY, .width = coreSide, .height = coreSide};

    // The pixels are produced in row-major order, so a running iterator replaces the
    // y * width + x index arithmetic and its unchecked operator[].
    auto out = img.alpha.begin();
    for (int y = 0; y < img.height; ++y) {
        for (int x = 0; x < img.width; ++x) {
            const PointF q{.x = x + 0.5, .y = y + 0.5};
            const double value = shadowAlpha(roundedRectSignedDistance(q, shape, p.cornerRadius), p);
            // Cut out the frame itself (antialiased over one pixel) so a translucent client
            // or the transparent area outside the rounded corners never shows the shadow.
            const double cut = std::clamp(roundedRectSignedDistance(q, coreRect, p.cornerRadius) + 0.5, 0.0, 1.0);
            const long a = std::lround(255.0 * value * cut);
            *out = static_cast<std::uint8_t>(std::clamp(a, 0L, 255L));
            ++out;
        }
    }
    return img;
}

} // namespace Kuura::Deco
