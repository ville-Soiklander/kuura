// Unit tests for src/shadow_logic.h (pure shadow computation of the Kuura window decoration).
//
// WHY these tests exist: they are written from the documented contract in shadow_logic.h
// ONLY, before and independently of shadow_logic.cpp. The rendered mask is checked three
// ways: (1) hand-computed pixel values on a tiny image, (2) structural properties the
// nine-slice stretching of KWin depends on (symmetry, identical edge rows/columns, monotonic
// falloff, transparent cut-out), and (3) a full per-pixel comparison against a LOCAL
// reference that re-evaluates the documented formulas with its own rounded-box distance.
//
// BUILD ASSUMPTION: the CMake target adds the generated directory (generated/cpp) to the
// include path, as kuura-frost does: <tokens.h> (Kuura::Tokens::kDecorationShadowSize, ...)
// and <token_colors.h> (Kuura::Tokens::Light::kShadow) are used to check shadowParams() on
// the shipped values. Everything else uses fixture values chosen here.
//
// Framework: plain C++20, no Qt, no external test library. main() returns non-zero on any
// failed check and prints every failure as file:line plus the compared values.

#include "shadow_logic.h"

#include <token_colors.h>
#include <tokens.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <type_traits>
#include <vector>

using namespace Kuura::Deco;

// ---- Tiny check helper (duplicated per test file on purpose: one self-contained file each)

namespace
{
int g_checks = 0;
int g_failures = 0;

/// Render a value for a failure message; enums print as their integer value.
template<typename T>
std::string show(const T &v)
{
    if constexpr (std::is_enum_v<T>) {
        return std::to_string(static_cast<long long>(v));
    } else {
        std::ostringstream os;
        os.precision(17);
        os << v;
        return os.str();
    }
}

/// Render a colour for failure messages.
std::string show(const Rgba &c)
{
    std::ostringstream os;
    os << "rgba(" << int(c.r) << "," << int(c.g) << "," << int(c.b) << "," << int(c.a) << ")";
    return os.str();
}

/// Record one boolean check; prints file:line and the expression text on failure.
void check(bool ok, const char *expr, const char *file, int line)
{
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << file << ":" << line << ": CHECK failed: " << expr << "\n";
    }
}

/// Record an equality check (exact comparison with ==).
template<typename A, typename B>
void checkEq(const A &a, const B &b, const char *ea, const char *eb, const char *file, int line)
{
    ++g_checks;
    if (!(a == b)) {
        ++g_failures;
        std::cerr << file << ":" << line << ": CHECK_EQ failed: " << ea << " == " << eb << " (got " << show(a)
                  << ", expected " << show(b) << ")\n";
    }
}

/// Record a floating-point closeness check; NaN never passes.
void checkNear(double a, double b, double eps, const char *ea, const char *eb, const char *file, int line)
{
    ++g_checks;
    if (!(std::fabs(a - b) <= eps)) {
        ++g_failures;
        std::cerr << file << ":" << line << ": CHECK_NEAR failed: " << ea << " ~ " << eb << " (got " << show(a)
                  << ", expected " << show(b) << ", eps " << show(eps) << ")\n";
    }
}

/// Record four closeness checks for margins (left, top, right, bottom).
void checkMargins(const MarginsF &m, double l, double t, double r, double b, const char *expr, const char *file, int line)
{
    checkNear(m.left, l, 1e-9, expr, "left", file, line);
    checkNear(m.top, t, 1e-9, expr, "top", file, line);
    checkNear(m.right, r, 1e-9, expr, "right", file, line);
    checkNear(m.bottom, b, 1e-9, expr, "bottom", file, line);
}

/// Record four closeness checks for a rectangle (x, y, width, height).
void checkRect(const RectF &r, double x, double y, double w, double h, const char *expr, const char *file, int line)
{
    checkNear(r.x, x, 1e-9, expr, "x", file, line);
    checkNear(r.y, y, 1e-9, expr, "y", file, line);
    checkNear(r.width, w, 1e-9, expr, "width", file, line);
    checkNear(r.height, h, 1e-9, expr, "height", file, line);
}
} // namespace

#define CHECK(cond) check((cond), #cond, __FILE__, __LINE__)
#define CHECK_EQ(a, b) checkEq((a), (b), #a, #b, __FILE__, __LINE__)
#define CHECK_NEAR(a, b, eps) checkNear((a), (b), (eps), #a, #b, __FILE__, __LINE__)
#define CHECK_MARGINS(m, l, t, r, b) checkMargins((m), (l), (t), (r), (b), #m, __FILE__, __LINE__)
#define CHECK_RECT(r, x, y, w, h) checkRect((r), (x), (y), (w), (h), #r, __FILE__, __LINE__)

// ---- Fixtures and a local reference ----------------------------------------------------

namespace
{
/// Valid fixture metrics; only shadowSize and cornerRadius matter to shadowParams().
Metrics metricsWith(double shadowSize, double cornerRadius)
{
    Metrics m;
    m.titleBarHeight = 36.0;
    m.buttonDiameter = 14.0;
    m.buttonSpacing = 8.0;
    m.buttonInset = 12.0;
    m.glyphStroke = 1.5;
    m.shadowSize = shadowSize;
    m.cornerRadius = cornerRadius;
    m.hairline = 1.0;
    m.captionGap = 12.0;
    return m;
}

/// A palette whose only meaningful field is the shadow colour (alpha = peak opacity).
ModePalette paletteWithShadow(std::uint8_t r, std::uint8_t g, std::uint8_t b, std::uint8_t a)
{
    ModePalette p;
    p.shadow = Rgba{r, g, b, a};
    return p;
}

/// Build ShadowParams directly, bypassing shadowParams(), so rendering tests do not depend
/// on it. The colour is a recognisable non-black value to check it is copied through.
ShadowParams makeParams(double extent, double offsetY, double peak, double radius)
{
    ShadowParams p;
    p.extent = extent;
    p.offsetY = offsetY;
    p.peakAlpha = peak;
    p.cornerRadius = radius;
    p.colour = Rgba{10, 20, 30, 40};
    return p;
}

/// Reference rounded-box signed distance (the "standard" formula the header names): distance
/// from point (px, py) to a box centred at (cx, cy) with half sizes (hw, hh), radius clamped
/// to [0, min(hw, hh)]. Deliberately a separate implementation from the one under test.
double refDistance(double px, double py, double cx, double cy, double hw, double hh, double radius)
{
    const double r = std::clamp(radius, 0.0, std::min(hw, hh));
    const double qx = std::fabs(px - cx) - (hw - r);
    const double qy = std::fabs(py - cy) - (hh - r);
    return std::hypot(std::max(qx, 0.0), std::max(qy, 0.0)) + std::min(std::max(qx, qy), 0.0) - r;
}

/// Reference shadow alpha, the documented continuous form 1 - (1 - peak)^((n - d) / n).
double refAlpha(double d, const ShadowParams &p)
{
    if (p.extent <= 0.0) {
        return 0.0;
    }
    if (d <= 0.0) {
        return p.peakAlpha;
    }
    if (d >= p.extent) {
        return 0.0;
    }
    return 1.0 - std::pow(1.0 - p.peakAlpha, (p.extent - d) / p.extent);
}

/// Everything the documented layout says about the image, computed independently.
struct RefLayout {
    double c;   ///< Half side of the core minus the centre pixel: core side = 2c + 1.
    double padL, padT, padR, padB;
    int width, height;
};

RefLayout refLayout(const ShadowParams &p)
{
    RefLayout l;
    l.c = std::ceil(p.cornerRadius) + std::ceil(p.offsetY) + 1.0;
    l.padL = p.extent;
    l.padT = std::max(0.0, p.extent - p.offsetY);
    l.padR = p.extent;
    l.padB = p.extent + p.offsetY;
    const double core = 2.0 * l.c + 1.0;
    l.width = static_cast<int>(std::lround(l.padL + core + l.padR));
    l.height = static_cast<int>(std::lround(l.padT + core + l.padB));
    return l;
}

/// Reference alpha byte of pixel (x, y) per the documented renderShadowImage() recipe.
int refPixel(const ShadowParams &p, const RefLayout &l, int x, int y)
{
    const double qx = x + 0.5;
    const double qy = y + 0.5;
    const double half = l.c + 0.5;                         // half side of the core
    const double coreCx = l.padL + half;                   // core centre
    const double coreCy = l.padT + half;
    const double shapeD = refDistance(qx, qy, coreCx, coreCy + p.offsetY, half, half, p.cornerRadius);
    const double value = refAlpha(shapeD, p);
    const double coreD = refDistance(qx, qy, coreCx, coreCy, half, half, p.cornerRadius);
    const double cut = std::clamp(coreD + 0.5, 0.0, 1.0);
    return static_cast<int>(std::lround(255.0 * value * cut));
}

/// Pixel accessor; an out-of-range access is recorded as a failure and returns 0.
int at(const ShadowImage &img, int x, int y)
{
    const bool inside = x >= 0 && y >= 0 && x < img.width && y < img.height;
    if (!inside) {
        // Only a failure is recorded, so loops over every pixel do not inflate the check count.
        check(false, "pixel coordinate inside the image", __FILE__, __LINE__);
        return 0;
    }
    return img.alpha[static_cast<std::size_t>(y) * static_cast<std::size_t>(img.width) + static_cast<std::size_t>(x)];
}

/// The main fixture: extent 12, offset 4, peak 0.4, radius 14.
/// c = 14 + 4 + 1 = 19, core side 39, padding {12, 8, 12, 16}, image 63 x 63,
/// innerShadowRect {31, 27, 1, 1}.
ShadowParams mainParams()
{
    return makeParams(12.0, 4.0, 0.4, 14.0);
}
} // namespace

// ---- shadowParams ----------------------------------------------------------------------

/// shadowParams(): offsetY = round(size / 4), extent = max(0, size - offsetY), peakAlpha =
/// palette.shadow.a / 255, cornerRadius = m.cornerRadius, colour = palette.shadow. Hand case:
/// size 16 -> offsetY 4, extent 12; alpha 0x66 = 102 -> 0.4; colour copied incl. alpha.
static void testShadowParamsBasic()
{
    const ShadowParams p = shadowParams(metricsWith(16.0, 14.0), paletteWithShadow(1, 2, 3, 0x66));
    CHECK_NEAR(p.offsetY, 4.0, 1e-12);
    CHECK_NEAR(p.extent, 12.0, 1e-12);
    CHECK_NEAR(p.peakAlpha, 102.0 / 255.0, 1e-12);
    CHECK_NEAR(p.cornerRadius, 14.0, 1e-12);
    CHECK_EQ(p.colour, (Rgba{1, 2, 3, 0x66}));
}

/// The offset rounding rule is round-half-away (std::round): size 2 -> 0.5 -> 1, 6 -> 1.5 ->
/// 2, 10 -> 2.5 -> 3, 16 -> 4, 1 -> 0.25 -> 0, 3 -> 0.75 -> 1, 5 -> 1.25 -> 1, 32 -> 8. Extent
/// is size - offset: 1, 4, 7, 12, 1, 2, 4, 24. WHY: banker's rounding would give 0 for size 2
/// and 2 for size 10, which breaks the QML parity the header promises.
static void testShadowParamsOffsetRounding()
{
    struct Row {
        double size, offset, extent;
    };
    const Row rows[] = {{2, 1, 1}, {6, 2, 4}, {10, 3, 7}, {16, 4, 12}, {1, 0, 1}, {3, 1, 2}, {5, 1, 4}, {32, 8, 24}};
    for (const Row &r : rows) {
        const ShadowParams p = shadowParams(metricsWith(r.size, 14.0), paletteWithShadow(0, 0, 0, 51));
        CHECK_NEAR(p.offsetY, r.offset, 1e-12);
        CHECK_NEAR(p.extent, r.extent, 1e-12);
    }
}

/// shadowSize 0 means "no shadow": extent 0 and offset 0. WHY: decoration.cpp uses
/// extent == 0 to decide to call setShadow(nullptr).
static void testShadowParamsNoShadow()
{
    const ShadowParams p = shadowParams(metricsWith(0.0, 14.0), paletteWithShadow(0, 0, 0, 51));
    CHECK_NEAR(p.extent, 0.0, 1e-12);
    CHECK_NEAR(p.offsetY, 0.0, 1e-12);
}

/// peakAlpha spans 0..1 with the palette alpha: 0 -> 0.0, 255 -> 1.0, 51 (0x33) -> 0.2.
static void testShadowParamsPeakAlpha()
{
    const Metrics m = metricsWith(16.0, 14.0);
    CHECK_NEAR(shadowParams(m, paletteWithShadow(0, 0, 0, 0)).peakAlpha, 0.0, 1e-12);
    CHECK_NEAR(shadowParams(m, paletteWithShadow(0, 0, 0, 255)).peakAlpha, 1.0, 1e-12);
    CHECK_NEAR(shadowParams(m, paletteWithShadow(0, 0, 0, 0x33)).peakAlpha, 0.2, 1e-12);
}

/// On the shipped tokens: offset = round(shadow_size / 4), extent = size - offset, peak =
/// light shadow alpha / 255. WHY constants instead of literals: stays valid when tokens
/// change. The mode palette is the shipped light one.
static void testShadowParamsFromTokens()
{
    const Metrics m = tokenMetrics();
    const ModePalette light = tokenPalette(Mode::Light);
    const ShadowParams p = shadowParams(m, light);
    const double size = static_cast<double>(Kuura::Tokens::kDecorationShadowSize);
    const double offset = std::round(size / 4.0);
    CHECK_NEAR(p.offsetY, offset, 1e-9);
    CHECK_NEAR(p.extent, std::max(0.0, size - offset), 1e-9);
    CHECK_NEAR(p.peakAlpha, static_cast<double>(Kuura::Tokens::Light::kShadow & 0xFFu) / 255.0, 1e-9);
    CHECK_NEAR(p.cornerRadius, static_cast<double>(Kuura::Tokens::kRadiusWindow), 1e-9);

    // The dark shadow is at least as strong as the light one in the shipped palette's own terms.
    const ShadowParams d = shadowParams(m, tokenPalette(Mode::Dark));
    CHECK_NEAR(d.peakAlpha, static_cast<double>(Kuura::Tokens::Dark::kShadow & 0xFFu) / 255.0, 1e-9);
}

// ---- shadowPadding ---------------------------------------------------------------------

/// shadowPadding(): {extent, max(0, extent - offsetY), extent, extent + offsetY}. extent 12,
/// offset 4 -> {12, 8, 12, 16}. The shape is shifted down, so the shadow reaches less far above
/// the window and further below it.
static void testShadowPadding()
{
    CHECK_MARGINS(shadowPadding(makeParams(12.0, 4.0, 0.4, 14.0)), 12.0, 8.0, 12.0, 16.0);
    CHECK_MARGINS(shadowPadding(makeParams(1.0, 0.0, 0.4, 0.0)), 1.0, 1.0, 1.0, 1.0);
    CHECK_MARGINS(shadowPadding(makeParams(24.0, 8.0, 0.4, 14.0)), 24.0, 16.0, 24.0, 32.0);
}

/// Top padding clamps to 0 when extent <= offsetY (never negative). Boundary: extent 4 /
/// offset 4 -> 0 exactly; extent 3 / offset 4 -> 0 (clamped from -1); extent 5 / offset 4 -> 1.
static void testShadowPaddingTopClamp()
{
    CHECK_MARGINS(shadowPadding(makeParams(5.0, 4.0, 0.4, 14.0)), 5.0, 1.0, 5.0, 9.0);
    CHECK_MARGINS(shadowPadding(makeParams(4.0, 4.0, 0.4, 14.0)), 4.0, 0.0, 4.0, 8.0);
    CHECK_MARGINS(shadowPadding(makeParams(3.0, 4.0, 0.4, 14.0)), 3.0, 0.0, 3.0, 7.0);
}

// ---- shadowAlpha -----------------------------------------------------------------------

/// shadowAlpha() with peak 0.4, extent 12: peak at distance <= 0 (inside the shape and exactly
/// on its edge), 0 at distance >= extent. Hand value at the half way point d = 6:
/// 1 - 0.6^0.5 = 1 - 0.7745966692 = 0.2254033308. At d = 3: 1 - 0.6^0.75.
static void testShadowAlphaKnownValues()
{
    const ShadowParams p = mainParams();
    CHECK_NEAR(shadowAlpha(-100.0, p), 0.4, 1e-12);
    CHECK_NEAR(shadowAlpha(-0.001, p), 0.4, 1e-12);
    CHECK_NEAR(shadowAlpha(0.0, p), 0.4, 1e-12);
    CHECK_NEAR(shadowAlpha(6.0, p), 0.2254033308, 1e-9);
    CHECK_NEAR(shadowAlpha(3.0, p), 1.0 - std::pow(0.6, 0.75), 1e-9);
    CHECK_NEAR(shadowAlpha(12.0, p), 0.0, 1e-12);
    CHECK_NEAR(shadowAlpha(12.5, p), 0.0, 1e-12);
    CHECK_NEAR(shadowAlpha(1000.0, p), 0.0, 1e-12);
}

/// Continuity at the extent: just inside the extent the value is tiny, not a jump. d = 11.999
/// -> 1 - 0.6^(0.001 / 12) ~ 4.3e-5. And just outside the peak: d = 0.001 is just below peak.
static void testShadowAlphaContinuity()
{
    const ShadowParams p = mainParams();
    CHECK(shadowAlpha(11.999, p) < 1e-3);
    CHECK(shadowAlpha(11.999, p) > 0.0);
    CHECK_NEAR(shadowAlpha(0.001, p), 0.4, 1e-3);
    CHECK(shadowAlpha(0.001, p) < 0.4);
}

/// Monotonic falloff: non-increasing everywhere on a fine sweep from -5 to 15, STRICTLY
/// decreasing inside (0, extent), and always within [0, peak]. WHY: a shadow that gets
/// brighter with distance, or overshoots the peak, would be visibly wrong.
static void testShadowAlphaMonotonic()
{
    const ShadowParams p = mainParams();
    double previous = shadowAlpha(-5.0, p);
    for (double d = -4.75; d <= 15.0; d += 0.25) {
        const double a = shadowAlpha(d, p);
        CHECK(a <= previous + 1e-12);
        CHECK(a >= 0.0);
        CHECK(a <= p.peakAlpha + 1e-12);
        if (d > 0.0 && d < p.extent) {
            CHECK(a < previous);
        }
        previous = a;
    }
}

/// Degenerate parameters: extent <= 0 -> 0 everywhere (also inside); peak 0 -> 0 everywhere;
/// peak 1 -> 1 inside the extent (0^x = 0 for x > 0) and 0 at the extent.
static void testShadowAlphaDegenerate()
{
    for (const double d : {-10.0, -0.5, 0.0, 0.5, 3.0, 100.0}) {
        CHECK_NEAR(shadowAlpha(d, makeParams(0.0, 4.0, 0.4, 14.0)), 0.0, 1e-12);
        CHECK_NEAR(shadowAlpha(d, makeParams(-3.0, 4.0, 0.4, 14.0)), 0.0, 1e-12);
        CHECK_NEAR(shadowAlpha(d, makeParams(12.0, 4.0, 0.0, 14.0)), 0.0, 1e-12);
    }
    const ShadowParams opaque = makeParams(12.0, 4.0, 1.0, 14.0);
    CHECK_NEAR(shadowAlpha(-1.0, opaque), 1.0, 1e-12);
    CHECK_NEAR(shadowAlpha(0.0, opaque), 1.0, 1e-12);
    CHECK_NEAR(shadowAlpha(6.0, opaque), 1.0, 1e-12);
    CHECK_NEAR(shadowAlpha(12.0, opaque), 0.0, 1e-12);
}

// ---- roundedRectSignedDistance ---------------------------------------------------------

/// Sign convention on a 100 x 50 rectangle with radius 10: centre (50, 25) -> -25 (nearest
/// edge is 25 away); points on the four edge midpoints -> 0; just outside -> positive; just
/// inside -> negative. Hand values: (50, 5) -> -5; (50, -5) -> 5; (110, 25) -> 10; (-3, 25) ->
/// 3.
static void testRoundedRectDistanceSigns()
{
    const RectF r{0.0, 0.0, 100.0, 50.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 25.0}, r, 10.0), -25.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 0.0}, r, 10.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 50.0}, r, 10.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{0.0, 25.0}, r, 10.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{100.0, 25.0}, r, 10.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 5.0}, r, 10.0), -5.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, -5.0}, r, 10.0), 5.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{110.0, 25.0}, r, 10.0), 10.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{-3.0, 25.0}, r, 10.0), 3.0, 1e-9);
    CHECK(roundedRectSignedDistance(PointF{50.0, 25.0}, r, 10.0) < 0.0);
    CHECK(roundedRectSignedDistance(PointF{50.0, 60.0}, r, 10.0) > 0.0);
}

/// Corner behaviour with radius 10: the arc centre is (10, 10). The nominal corner (0, 0) is
/// outside the rounded shape by sqrt(200) - 10 = 4.1421356; the arc point on the diagonal
/// (10 - 10 / sqrt2, 10 - 10 / sqrt2) = (2.9289322, 2.9289322) is on the outline (0); the arc
/// centre itself is at -10. WHY: distinguishes a rounded box from a plain rectangle.
static void testRoundedRectDistanceCorner()
{
    const RectF r{0.0, 0.0, 100.0, 50.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{0.0, 0.0}, r, 10.0), std::sqrt(200.0) - 10.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{2.9289322, 2.9289322}, r, 10.0), 0.0, 1e-6);
    CHECK_NEAR(roundedRectSignedDistance(PointF{10.0, 10.0}, r, 10.0), -10.0, 1e-9);
    // Same corner at the opposite end (bottom-right), by symmetry.
    CHECK_NEAR(roundedRectSignedDistance(PointF{100.0, 50.0}, r, 10.0), std::sqrt(200.0) - 10.0, 1e-9);
}

/// Radius 0 gives plain Euclidean rectangle distance: (-3, -4) from the corner -> 5. A negative
/// radius is clamped to 0 (same result). A rectangle not at the origin only shifts the result:
/// {10, 20, 100, 50} has its centre at (60, 45), so the centre is still -25.
static void testRoundedRectDistanceSquareAndShifted()
{
    const RectF r{0.0, 0.0, 100.0, 50.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{-3.0, -4.0}, r, 0.0), 5.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{-3.0, -4.0}, r, -5.0), 5.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{0.0, 0.0}, r, 0.0), 0.0, 1e-9);

    const RectF shifted{10.0, 20.0, 100.0, 50.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{60.0, 45.0}, shifted, 10.0), -25.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{60.0, 15.0}, shifted, 10.0), 5.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{10.0, 45.0}, shifted, 10.0), 0.0, 1e-9);
}

/// The radius is clamped to min(width, height) / 2. On 100 x 50 a radius of 100 behaves like 25
/// (a stadium): centre -> -25, edge midpoints -> 0, (-5, 25) -> 5, and results equal those of
/// radius 25 at several points. A square of 40 x 40 with a huge radius is a circle of radius 20:
/// centre -> -20, (50, 20) -> 10.
static void testRoundedRectDistanceRadiusClamp()
{
    const RectF r{0.0, 0.0, 100.0, 50.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 25.0}, r, 100.0), -25.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 0.0}, r, 100.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{0.0, 25.0}, r, 100.0), 0.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{-5.0, 25.0}, r, 100.0), 5.0, 1e-9);
    for (const PointF p : {PointF{0.0, 0.0}, PointF{10.0, 5.0}, PointF{50.0, 25.0}, PointF{95.0, 40.0}, PointF{120.0, 30.0}}) {
        CHECK_NEAR(roundedRectSignedDistance(p, r, 100.0), roundedRectSignedDistance(p, r, 25.0), 1e-9);
    }

    const RectF square{0.0, 0.0, 40.0, 40.0};
    CHECK_NEAR(roundedRectSignedDistance(PointF{20.0, 20.0}, square, 1000.0), -20.0, 1e-9);
    CHECK_NEAR(roundedRectSignedDistance(PointF{50.0, 20.0}, square, 1000.0), 10.0, 1e-9);
}

// ---- renderShadowImage -----------------------------------------------------------------

/// Dimensions and placement data of the main fixture: c = ceil(14) + ceil(4) + 1 = 19, core
/// side 39; padding {12, 8, 12, 16}; image 39 + 24 = 63 wide and 39 + 8 + 16 = 63 high;
/// innerShadowRect {12 + 19, 8 + 19, 1, 1} = {31, 27, 1, 1}; padding equals shadowPadding();
/// the colour is copied; alpha holds width * height bytes.
static void testRenderDimensionsAndPlacement()
{
    const ShadowParams p = mainParams();
    const ShadowImage img = renderShadowImage(p);
    CHECK_EQ(img.width, 63);
    CHECK_EQ(img.height, 63);
    CHECK_EQ(img.alpha.size(), std::size_t{63} * std::size_t{63});
    CHECK_RECT(img.innerShadowRect, 31.0, 27.0, 1.0, 1.0);
    CHECK_MARGINS(img.padding, 12.0, 8.0, 12.0, 16.0);
    CHECK_EQ(img.colour, p.colour);
}

/// A fractional radius is rounded UP for the core size (ceil): radius 5.5, offset 2, extent 6
/// -> c = 6 + 2 + 1 = 9, core 19, padding {6, 4, 6, 8}, image 19 + 12 = 31 wide and
/// 19 + 4 + 8 = 31 high, inner {6 + 9, 4 + 9, 1, 1} = {15, 13, 1, 1}. And extent < offset:
/// extent 3 / offset 4 / radius 2 -> c = 2 + 4 + 1 = 7, core 15, padding {3, 0, 3, 7}, image
/// 21 x 22, inner {10, 7, 1, 1}.
static void testRenderDimensionsFractionalRadiusAndTopClamp()
{
    const ShadowImage a = renderShadowImage(makeParams(6.0, 2.0, 0.5, 5.5));
    CHECK_EQ(a.width, 31);
    CHECK_EQ(a.height, 31);
    CHECK_EQ(a.alpha.size(), std::size_t{31} * std::size_t{31});
    CHECK_RECT(a.innerShadowRect, 15.0, 13.0, 1.0, 1.0);
    CHECK_MARGINS(a.padding, 6.0, 4.0, 6.0, 8.0);

    const ShadowImage b = renderShadowImage(makeParams(3.0, 4.0, 0.5, 2.0));
    CHECK_EQ(b.width, 21);
    CHECK_EQ(b.height, 22);
    CHECK_EQ(b.alpha.size(), std::size_t{21} * std::size_t{22});
    CHECK_RECT(b.innerShadowRect, 10.0, 7.0, 1.0, 1.0);
    CHECK_MARGINS(b.padding, 3.0, 0.0, 3.0, 7.0);
}

/// Tiny image computed fully by hand: extent 1, offset 0, peak 0.5, radius 0 -> c = 1, core 3
/// x 3, padding 1 on every side, image 5 x 5, inner {2, 2, 1, 1}.
///  - all nine core pixels sit at least 0.5 inside the frame -> cut-out 0 -> alpha 0;
///  - edge neighbour (0, 2): centre (0.5, 2.5) is 0.5 from the shape; value = 1 - 0.5^(0.5) =
///    0.292893 -> 255 * 0.292893 = 74.7 -> 75;
///  - corner (0, 0): distance sqrt(0.5) = 0.7071; value = 1 - 0.5^(1 - 0.7071) = 0.18377 ->
///    46.9 -> 47. Tolerance +-1 on the rounded byte.
static void testRenderTinyImageByHand()
{
    const ShadowImage img = renderShadowImage(makeParams(1.0, 0.0, 0.5, 0.0));
    CHECK_EQ(img.width, 5);
    CHECK_EQ(img.height, 5);
    CHECK_EQ(img.alpha.size(), std::size_t{25});
    CHECK_RECT(img.innerShadowRect, 2.0, 2.0, 1.0, 1.0);
    if (img.alpha.size() != 25) {
        return;
    }
    for (int y = 1; y <= 3; ++y) {
        for (int x = 1; x <= 3; ++x) {
            CHECK_EQ(at(img, x, y), 0);
        }
    }
    CHECK_NEAR(at(img, 0, 2), 75.0, 1.0);
    CHECK_NEAR(at(img, 4, 2), 75.0, 1.0);
    CHECK_NEAR(at(img, 2, 0), 75.0, 1.0);
    CHECK_NEAR(at(img, 2, 4), 75.0, 1.0);
    CHECK_NEAR(at(img, 0, 0), 47.0, 1.0);
    CHECK_NEAR(at(img, 4, 4), 47.0, 1.0);
    CHECK_NEAR(at(img, 0, 4), 47.0, 1.0);
    CHECK_NEAR(at(img, 4, 0), 47.0, 1.0);
}

/// The cut-out: the centre pixel (the one innerShadowRect names) is fully transparent, and so
/// is every pixel deep inside the frame, for the main fixture. WHY: a translucent client or
/// the transparent corner of the rounded frame must not show the shadow through it. "Deep
/// inside" = the core shrunk by radius + 1 on every side: x in [12 + 15, 51 - 15), y in
/// [8 + 15, 47 - 15).
static void testRenderCutOutIsTransparent()
{
    const ShadowImage img = renderShadowImage(mainParams());
    CHECK_EQ(at(img, 31, 27), 0);
    for (int y = 23; y < 32; ++y) {
        for (int x = 27; x < 36; ++x) {
            CHECK_EQ(at(img, x, y), 0);
        }
    }
    // Immediately outside the straight bottom edge of the frame the shadow is opaque-ish.
    CHECK(at(img, 31, 47) > 0);
    CHECK(at(img, 31, 46) == 0); // the last core row: 0.5 inside the edge -> cut-out 0
}

/// Peak and falloff on the straight bottom edge (main fixture). The core ends at image row 47
/// (core y in [8, 47)); the shape is moved down by 4 so rows 47..50 are still inside it
/// (distance < 0) -> value = peak = 0.4 -> byte round(255 * 0.4) = 102. Row 62 centre is 11.5
/// below the shape bottom (51): value = 1 - 0.6^(0.5 / 12) = 0.021063 -> 5.4 -> 5. The top
/// row 0 is also 11.5 from the shape top (12) -> 5.
static void testRenderPeakAndEdgeValues()
{
    const ShadowImage img = renderShadowImage(mainParams());
    for (int y = 47; y <= 50; ++y) {
        CHECK_NEAR(at(img, 31, y), 102.0, 1.0);
    }
    CHECK_NEAR(at(img, 31, 62), 5.0, 1.0);
    CHECK_NEAR(at(img, 31, 0), 5.0, 1.0);
    // Row 51 is 0.5 below the shape bottom: value = 1 - 0.6^(11.5 / 12) = 0.3871 -> byte ~99
    // (ln 0.6 = -0.5108, * 0.95833 = -0.4895, exp = 0.6129).
    const double expected51 = 255.0 * (1.0 - std::exp((11.5 / 12.0) * std::log(0.6)));
    CHECK_NEAR(at(img, 31, 51), expected51, 1.0);

    // No byte exceeds the peak byte anywhere, and the peak is reached.
    int maxByte = 0;
    for (const std::uint8_t v : img.alpha) {
        maxByte = std::max(maxByte, static_cast<int>(v));
    }
    CHECK(maxByte <= 102 + 1);
    CHECK(maxByte >= 102 - 1);
}

/// Strictly speaking monotone profile away from the frame along the four axes through the
/// centre (non-increasing with distance): down from row 47 to 62, up from row 7 to 0, right
/// from column 51 to 62 and left from column 11 to 0. WHY: the stretched edge slices are what
/// KWin repeats, so a non-monotone profile would show as banding.
static void testRenderMonotonicAwayFromFrame()
{
    const ShadowImage img = renderShadowImage(mainParams());
    for (int y = 48; y < 63; ++y) {
        CHECK(at(img, 31, y) <= at(img, 31, y - 1));
    }
    for (int y = 6; y >= 0; --y) {
        CHECK(at(img, 31, y) <= at(img, 31, y + 1));
    }
    for (int x = 52; x < 63; ++x) {
        CHECK(at(img, x, 27) <= at(img, x - 1, 27));
    }
    for (int x = 10; x >= 0; --x) {
        CHECK(at(img, x, 27) <= at(img, x + 1, 27));
    }
}

/// Left/right mirror symmetry: the padding is equal on both sides and the shape is
/// symmetric, so alpha(x, y) == alpha(width - 1 - x, y) (within one byte of rounding noise).
static void testRenderLeftRightSymmetry()
{
    for (const ShadowParams &p : {mainParams(), makeParams(6.0, 2.0, 0.5, 5.5), makeParams(3.0, 4.0, 0.5, 2.0)}) {
        const ShadowImage img = renderShadowImage(p);
        for (int y = 0; y < img.height; ++y) {
            for (int x = 0; x < img.width / 2; ++x) {
                CHECK_NEAR(at(img, x, y), at(img, img.width - 1 - x, y), 1.0);
            }
        }
    }
}

/// Nine-slice validity (main fixture): KWin stretches the edge slices, so (a) every row must
/// be identical across the straight part of the top/bottom edges (columns 26..36, the shape
/// and the cut-out are straight there: |x + 0.5 - 31.5| <= 14 ... exactly the columns with no
/// corner influence) and (b) every column identical across rows 26..32 (the rows where both
/// the shape, moved down by 4, and the core are straight), including the row/column of
/// innerShadowRect (27 / 31). Equality is exact: the stretched pixels are copies.
static void testRenderEdgesAreStretchable()
{
    const ShadowImage img = renderShadowImage(mainParams());
    for (int y = 0; y < img.height; ++y) {
        const int reference = at(img, 31, y);
        for (int x = 26; x <= 36; ++x) {
            CHECK_EQ(at(img, x, y), reference);
        }
    }
    for (int x = 0; x < img.width; ++x) {
        const int reference = at(img, x, 27);
        for (int y = 26; y <= 32; ++y) {
            CHECK_EQ(at(img, x, y), reference);
        }
    }
}

/// Full per-pixel comparison with the local reference implementation of the documented
/// recipe (shape = core moved down by offset, value = shadowAlpha(signed distance), cut-out =
/// clamp(core distance + 0.5, 0, 1), alpha = round(255 * value * cut-out)), for several
/// parameter sets, including a fractional radius, extent < offset (zero top padding), an
/// offset of 0, and peak 1. Tolerance one byte for floating-point rounding at .5 boundaries.
static void testRenderMatchesReferenceRecipe()
{
    const ShadowParams sets[] = {
        mainParams(),
        makeParams(6.0, 2.0, 0.5, 5.5),
        makeParams(3.0, 4.0, 0.5, 2.0),
        makeParams(10.0, 0.0, 0.3, 5.5),
        makeParams(1.0, 0.0, 0.5, 0.0),
        makeParams(8.0, 3.0, 1.0, 8.0),
        makeParams(24.0, 8.0, 0.4, 14.0),
    };
    for (const ShadowParams &p : sets) {
        const RefLayout l = refLayout(p);
        const ShadowImage img = renderShadowImage(p);
        CHECK_EQ(img.width, l.width);
        CHECK_EQ(img.height, l.height);
        CHECK_EQ(img.alpha.size(), static_cast<std::size_t>(l.width) * static_cast<std::size_t>(l.height));
        CHECK_RECT(img.innerShadowRect, l.padL + l.c, l.padT + l.c, 1.0, 1.0);
        CHECK_MARGINS(img.padding, l.padL, l.padT, l.padR, l.padB);
        CHECK_EQ(img.colour, p.colour);
        if (img.width != l.width || img.height != l.height || img.alpha.size() != static_cast<std::size_t>(l.width) * static_cast<std::size_t>(l.height)) {
            continue;
        }
        int mismatches = 0;
        for (int y = 0; y < l.height; ++y) {
            for (int x = 0; x < l.width; ++x) {
                if (std::abs(at(img, x, y) - refPixel(p, l, x, y)) > 1) {
                    ++mismatches;
                    if (mismatches <= 5) {
                        std::cerr << "  pixel (" << x << "," << y << ") got " << at(img, x, y) << " reference " << refPixel(p, l, x, y)
                                  << " for extent " << p.extent << " offset " << p.offsetY << " peak " << p.peakAlpha << " radius "
                                  << p.cornerRadius << "\n";
                    }
                }
            }
        }
        CHECK_EQ(mismatches, 0);
    }
}

/// Disabled shadow: extent <= 0 or peak <= 0 gives a 0 x 0 image with no pixels (the caller
/// then removes the shadow). Boundary: extent 1 / peak tiny positive IS rendered.
static void testRenderDisabled()
{
    const ShadowParams disabled[] = {
        makeParams(0.0, 0.0, 0.4, 14.0),
        makeParams(0.0, 4.0, 0.4, 14.0),
        makeParams(-3.0, 4.0, 0.4, 14.0),
        makeParams(12.0, 4.0, 0.0, 14.0),
        makeParams(12.0, 4.0, -0.1, 14.0),
        makeParams(0.0, 0.0, 0.0, 0.0),
    };
    for (const ShadowParams &p : disabled) {
        const ShadowImage img = renderShadowImage(p);
        CHECK_EQ(img.width, 0);
        CHECK_EQ(img.height, 0);
        CHECK(img.alpha.empty());
    }

    const ShadowImage barely = renderShadowImage(makeParams(1.0, 0.0, 0.001, 0.0));
    CHECK_EQ(barely.width, 5);
    CHECK_EQ(barely.height, 5);
    CHECK_EQ(barely.alpha.size(), std::size_t{25});
}

/// The colour is copied through unchanged, whatever its alpha (the alpha is ignored by the
/// renderer; peakAlpha governs). Uses two different colours to avoid a constant default.
static void testRenderCopiesColour()
{
    ShadowParams p = mainParams();
    p.colour = Rgba{200, 100, 50, 7};
    CHECK_EQ(renderShadowImage(p).colour, (Rgba{200, 100, 50, 7}));
    p.colour = Rgba{0, 0, 0, 255};
    CHECK_EQ(renderShadowImage(p).colour, (Rgba{0, 0, 0, 255}));
}

int main()
{
    testShadowParamsBasic();
    testShadowParamsOffsetRounding();
    testShadowParamsNoShadow();
    testShadowParamsPeakAlpha();
    testShadowParamsFromTokens();
    testShadowPadding();
    testShadowPaddingTopClamp();
    testShadowAlphaKnownValues();
    testShadowAlphaContinuity();
    testShadowAlphaMonotonic();
    testShadowAlphaDegenerate();
    testRoundedRectDistanceSigns();
    testRoundedRectDistanceCorner();
    testRoundedRectDistanceSquareAndShifted();
    testRoundedRectDistanceRadiusClamp();
    testRenderDimensionsAndPlacement();
    testRenderDimensionsFractionalRadiusAndTopClamp();
    testRenderTinyImageByHand();
    testRenderCutOutIsTransparent();
    testRenderPeakAndEdgeValues();
    testRenderMonotonicAwayFromFrame();
    testRenderLeftRightSymmetry();
    testRenderEdgesAreStretchable();
    testRenderMatchesReferenceRecipe();
    testRenderDisabled();
    testRenderCopiesColour();

    if (g_failures != 0) {
        std::cerr << g_failures << " of " << g_checks << " checks FAILED\n";
        return 1;
    }
    std::cout << g_checks << " checks passed\n";
    return 0;
}
