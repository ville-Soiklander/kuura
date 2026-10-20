// Unit tests for src/geometry.h (pure layout logic of the Kuura window decoration).
//
// WHY these tests exist: they are written from the documented contract in geometry.h
// ONLY, before and independently of geometry.cpp, so that a mistake in the implementation
// (off-by-one on a half-open edge, wrong rounding, a clamp that is missing) is caught
// instead of being repeated in the test. Expected values are derived by hand in the
// comments of each test; where the contract says "reads the generated tokens", the test
// compares against the generated Kuura::Tokens constants (not literals) so it stays valid
// when design/tokens.json changes.
//
// BUILD ASSUMPTION: the CMake target adds the generated directory (generated/cpp, which
// holds tokens.h) to the include path, as kuura-frost does, and src/ for geometry.h.
//
// Framework: plain C++20, no Qt, no external test library. main() returns non-zero on any
// failed check and prints every failure as file:line plus the compared values.

#include "geometry.h"

#include <tokens.h>

#include <array>
#include <cmath>
#include <cstddef>
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

/// Record four closeness checks for a rectangle (x, y, width, height).
void checkRect(const RectF &r, double x, double y, double w, double h, const char *expr, const char *file, int line)
{
    checkNear(r.x, x, 1e-9, expr, "x", file, line);
    checkNear(r.y, y, 1e-9, expr, "y", file, line);
    checkNear(r.width, w, 1e-9, expr, "width", file, line);
    checkNear(r.height, h, 1e-9, expr, "height", file, line);
}

/// Record four closeness checks for margins (left, top, right, bottom).
void checkMargins(const MarginsF &m, double l, double t, double r, double b, const char *expr, const char *file, int line)
{
    checkNear(m.left, l, 1e-9, expr, "left", file, line);
    checkNear(m.top, t, 1e-9, expr, "top", file, line);
    checkNear(m.right, r, 1e-9, expr, "right", file, line);
    checkNear(m.bottom, b, 1e-9, expr, "bottom", file, line);
}
} // namespace

#define CHECK(cond) check((cond), #cond, __FILE__, __LINE__)
#define CHECK_EQ(a, b) checkEq((a), (b), #a, #b, __FILE__, __LINE__)
#define CHECK_NEAR(a, b, eps) checkNear((a), (b), (eps), #a, #b, __FILE__, __LINE__)
#define CHECK_RECT(r, x, y, w, h) checkRect((r), (x), (y), (w), (h), #r, __FILE__, __LINE__)
#define CHECK_MARGINS(m, l, t, r, b) checkMargins((m), (l), (t), (r), (b), #m, __FILE__, __LINE__)

// ---- Fixtures --------------------------------------------------------------------------

namespace
{
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();

/// Valid fixture metrics, deliberately NOT the shipped token values so a test passes only
/// if the function uses its argument and not a hidden constant.
/// bar 36, disc 14 -> centring offset (36 - 14) / 2 = 11 exactly.
Metrics baseMetrics()
{
    Metrics m;
    m.titleBarHeight = 36.0;
    m.buttonDiameter = 14.0;
    m.buttonSpacing = 8.0;
    m.buttonInset = 12.0;
    m.glyphStroke = 1.5;
    m.shadowSize = 16.0;
    m.cornerRadius = 14.0;
    m.hairline = 1.0;
    m.captionGap = 12.0;
    return m;
}

/// isValid() of the base metrics with one field replaced.
bool validWith(double Metrics::*field, double value)
{
    Metrics m = baseMetrics();
    m.*field = value;
    return isValid(m);
}
} // namespace

// ---- Header constants ------------------------------------------------------------------

/// Pins the non-token design constants named in the header. WHY: the layout tests below
/// hard-code 4 / 1 / 3 in their expected values; if a constant is changed in the header the
/// failure must point here first instead of at dozens of derived checks.
static void testDesignConstants()
{
    CHECK_NEAR(kNormalBorder, 4.0, 0.0);
    CHECK_NEAR(kThinBorder, 1.0, 0.0);
    CHECK_NEAR(kResizeOnlyBorder, 3.0, 0.0);
    CHECK_NEAR(kTopResizeStrip, 4.0, 0.0);
    CHECK_NEAR(kHoverSlack, 4.0, 0.0);
    CHECK_NEAR(kCloseBarFactor, 0.42, 0.0);
    CHECK_NEAR(kMinimizeBarFactor, 0.35, 0.0);
    CHECK_NEAR(kGlyphGrid, 12.0, 0.0);
}

// ---- tokenMetrics / isValid ------------------------------------------------------------

/// tokenMetrics() must mirror the generated token constants one to one and be valid.
/// WHY: tokens.json is the single source of truth (header: "no token value is ever written
/// as a literal in this package"); comparing with the constants, not literals, keeps the
/// test valid when tokens change, and isValid() catches a shipped token out of range.
static void testTokenMetrics()
{
    const Metrics m = tokenMetrics();
    CHECK_NEAR(m.titleBarHeight, static_cast<double>(Kuura::Tokens::kDecorationTitlebarHeight), 1e-6);
    CHECK_NEAR(m.buttonDiameter, static_cast<double>(Kuura::Tokens::kDecorationButtonDiameter), 1e-6);
    CHECK_NEAR(m.buttonSpacing, static_cast<double>(Kuura::Tokens::kDecorationButtonSpacing), 1e-6);
    CHECK_NEAR(m.buttonInset, static_cast<double>(Kuura::Tokens::kDecorationButtonInset), 1e-6);
    CHECK_NEAR(m.glyphStroke, static_cast<double>(Kuura::Tokens::kDecorationGlyphStroke), 1e-6);
    CHECK_NEAR(m.shadowSize, static_cast<double>(Kuura::Tokens::kDecorationShadowSize), 1e-6);
    CHECK_NEAR(m.cornerRadius, static_cast<double>(Kuura::Tokens::kRadiusWindow), 1e-6);
    CHECK_NEAR(m.hairline, static_cast<double>(Kuura::Tokens::kStrokeHairline), 1e-6);
    CHECK_NEAR(m.captionGap, static_cast<double>(Kuura::Tokens::kSpacingGutter), 1e-6);
    CHECK(isValid(m));
}

/// The fixture itself must be valid, otherwise every "invalid because of X" check below
/// would be meaningless (it could be invalid for another reason).
static void testBaseMetricsValid()
{
    CHECK(isValid(baseMetrics()));
}

/// Every documented range of isValid() is tested one step below the lower limit, on both
/// limits, and one step above the upper limit. WHY: an off-by-one (< vs <=) in a range is the
/// most likely implementation mistake and passes any test that only uses mid-range values.
static void testIsValidRanges()
{
    struct Row {
        const char *name;
        double Metrics::*field;
        double belowLow, low, high, aboveHigh;
    };
    const Row rows[] = {
        {"titleBarHeight", &Metrics::titleBarHeight, 23.0, 24.0, 64.0, 65.0},
        {"buttonDiameter", &Metrics::buttonDiameter, 7.0, 8.0, 20.0, 21.0},
        {"buttonSpacing", &Metrics::buttonSpacing, -1.0, 0.0, 24.0, 25.0},
        {"buttonInset", &Metrics::buttonInset, -1.0, 0.0, 32.0, 33.0},
        {"glyphStroke", &Metrics::glyphStroke, 0.49, 0.5, 3.0, 3.01},
        {"shadowSize", &Metrics::shadowSize, -1.0, 0.0, 32.0, 33.0},
    };
    for (const Row &r : rows) {
        const bool belowLow = validWith(r.field, r.belowLow);
        const bool low = validWith(r.field, r.low);
        const bool high = validWith(r.field, r.high);
        const bool aboveHigh = validWith(r.field, r.aboveHigh);
        if (belowLow || !low || !high || aboveHigh) {
            std::cerr << "range row " << r.name << ": belowLow=" << belowLow << " low=" << low << " high=" << high
                      << " aboveHigh=" << aboveHigh << "\n";
        }
        CHECK(!belowLow);
        CHECK(low);
        CHECK(high);
        CHECK(!aboveHigh);
    }
}

/// cornerRadius: >= 0 and <= titleBarHeight; the upper bound moves with titleBarHeight.
/// WHY: "radius.window must not exceed titleBarHeight" is relative, so it is checked at two
/// different bar heights (36 and the minimum 24) to catch a hard-coded limit.
static void testIsValidCornerRadius()
{
    CHECK(!validWith(&Metrics::cornerRadius, -1.0));
    CHECK(validWith(&Metrics::cornerRadius, 0.0));
    CHECK(validWith(&Metrics::cornerRadius, 36.0));  // == titleBarHeight
    CHECK(!validWith(&Metrics::cornerRadius, 37.0)); // titleBarHeight + 1

    Metrics m = baseMetrics();
    m.titleBarHeight = 24.0;
    m.cornerRadius = 24.0;
    CHECK(isValid(m));
    m.cornerRadius = 25.0;
    CHECK(!isValid(m));
}

/// hairline must be strictly positive; captionGap non-negative without an upper bound.
/// WHY: a zero hairline would make outlineThickness() depend only on the scale floor, and
/// the two rules have different comparison operators (> 0 versus >= 0).
static void testIsValidHairlineAndGap()
{
    CHECK(!validWith(&Metrics::hairline, 0.0));
    CHECK(!validWith(&Metrics::hairline, -1.0));
    CHECK(validWith(&Metrics::hairline, 0.01));
    CHECK(validWith(&Metrics::hairline, 1.0));

    CHECK(!validWith(&Metrics::captionGap, -1.0));
    CHECK(validWith(&Metrics::captionGap, 0.0));
    CHECK(validWith(&Metrics::captionGap, 100.0));
}

/// Every field must reject NaN and +-infinity ("every value finite"). WHY: a NaN fails
/// ordinary range comparisons in the "wrong" direction (NaN < x and NaN > x are both false),
/// so a naive `if (v < lo || v > hi) return false` accepts it.
static void testIsValidRejectsNonFinite()
{
    double Metrics::*const fields[] = {
        &Metrics::titleBarHeight, &Metrics::buttonDiameter, &Metrics::buttonSpacing,
        &Metrics::buttonInset,    &Metrics::glyphStroke,    &Metrics::shadowSize,
        &Metrics::cornerRadius,   &Metrics::hairline,       &Metrics::captionGap,
    };
    for (double Metrics::*f : fields) {
        CHECK(!validWith(f, kNaN));
        CHECK(!validWith(f, kInf));
        CHECK(!validWith(f, -kInf));
    }
}

// ---- isEmpty / contains ----------------------------------------------------------------

/// isEmpty(): width <= 0 or height <= 0, both sides of zero.
static void testIsEmpty()
{
    CHECK(!isEmpty(RectF{0, 0, 1, 1}));
    CHECK(!isEmpty(RectF{5, 5, 0.001, 0.001}));
    CHECK(isEmpty(RectF{0, 0, 0, 10}));
    CHECK(isEmpty(RectF{0, 0, 10, 0}));
    CHECK(isEmpty(RectF{0, 0, -1, 10}));
    CHECK(isEmpty(RectF{0, 0, 10, -1}));
    CHECK(isEmpty(RectF{}));
}

/// contains() is half-open like QRectF::contains: left/top edges inside, right/bottom outside.
/// WHY: the hit test of the title bar and hover zone must agree with Qt's own rule, otherwise
/// the last pixel column flickers between hovered and not hovered. Rect {10,20,30,40} spans
/// x in [10,40), y in [20,60).
static void testContainsHalfOpen()
{
    const RectF r{10.0, 20.0, 30.0, 40.0};
    CHECK(contains(r, PointF{10.0, 20.0}));     // top-left corner: inside
    CHECK(contains(r, PointF{39.999, 59.999})); // just inside bottom-right
    CHECK(contains(r, PointF{25.0, 40.0}));     // middle
    CHECK(!contains(r, PointF{40.0, 30.0}));    // right edge: outside
    CHECK(!contains(r, PointF{20.0, 60.0}));    // bottom edge: outside
    CHECK(!contains(r, PointF{40.0, 60.0}));    // bottom-right corner: outside
    CHECK(!contains(r, PointF{9.999, 30.0}));   // just left
    CHECK(!contains(r, PointF{20.0, 19.999}));  // just above
}

/// An empty rectangle contains nothing, not even its own origin ("r is not empty and ...").
static void testContainsEmptyRect()
{
    CHECK(!contains(RectF{10, 10, 0, 5}, PointF{10, 10}));
    CHECK(!contains(RectF{10, 10, 5, 0}, PointF{10, 10}));
    CHECK(!contains(RectF{10, 10, -5, 5}, PointF{8, 12}));
    CHECK(!contains(RectF{}, PointF{0, 0}));
}

// ---- Borders ---------------------------------------------------------------------------

/// frameBorders(): top is always the title bar height; sides/bottom by preset; all zero
/// (except top) when maximized. Expected: Normal {4,H,4,4}, NoSides {1,H,1,4}, None {1,H,1,1}.
/// WHY three bar heights: the top must come from the metrics, not from a constant.
static void testFrameBorders()
{
    for (const double bar : {24.0, 36.0, 64.0}) {
        Metrics m = baseMetrics();
        m.titleBarHeight = bar;
        CHECK_MARGINS(frameBorders(m, BorderPreset::Normal, false), 4.0, bar, 4.0, 4.0);
        CHECK_MARGINS(frameBorders(m, BorderPreset::NoSides, false), 1.0, bar, 1.0, 4.0);
        CHECK_MARGINS(frameBorders(m, BorderPreset::None, false), 1.0, bar, 1.0, 1.0);
        CHECK_MARGINS(frameBorders(m, BorderPreset::Normal, true), 0.0, bar, 0.0, 0.0);
        CHECK_MARGINS(frameBorders(m, BorderPreset::NoSides, true), 0.0, bar, 0.0, 0.0);
        CHECK_MARGINS(frameBorders(m, BorderPreset::None, true), 0.0, bar, 0.0, 0.0);
    }
}

/// resizeOnlyBorders(): None -> 3 on left/right/bottom, NoSides -> 3 on left/right, Normal ->
/// 0; top always 0; a maximized direction zeroes the sides it covers (horizontal -> left and
/// right, vertical -> bottom). The 12-row table is written out literally (no formula) so a
/// swapped horizontal/vertical flag cannot hide behind a mirrored implementation.
static void testResizeOnlyBorders()
{
    struct Row {
        BorderPreset preset;
        bool maxH, maxV;
        double l, r, b;
    };
    const Row rows[] = {
        {BorderPreset::None, false, false, 3, 3, 3},
        {BorderPreset::None, true, false, 0, 0, 3},
        {BorderPreset::None, false, true, 3, 3, 0},
        {BorderPreset::None, true, true, 0, 0, 0},
        {BorderPreset::NoSides, false, false, 3, 3, 0},
        {BorderPreset::NoSides, true, false, 0, 0, 0},
        {BorderPreset::NoSides, false, true, 3, 3, 0},
        {BorderPreset::NoSides, true, true, 0, 0, 0},
        {BorderPreset::Normal, false, false, 0, 0, 0},
        {BorderPreset::Normal, true, false, 0, 0, 0},
        {BorderPreset::Normal, false, true, 0, 0, 0},
        {BorderPreset::Normal, true, true, 0, 0, 0},
    };
    for (const Row &row : rows) {
        const MarginsF got = resizeOnlyBorders(row.preset, row.maxH, row.maxV);
        CHECK_MARGINS(got, row.l, 0.0, row.r, row.b);
    }
}

// ---- Title bar -------------------------------------------------------------------------

/// titleBarRect(): floating -> {borders.left, 4, W - left - right, bar - 4}. W 400, Normal
/// borders 4/4 -> {4, 4, 392, 32}. WHY the y = 4 strip: updateSectionUnderMouse() tests the
/// title bar before the top border, so a bar starting at y = 0 makes the top edge unresizable
/// (header DEVIATION). Thin borders: x = 1, width 400 - 2 = 398. Bar 64 -> height 60, bar 24
/// -> 20 (the height comes from the metrics).
static void testTitleBarRect()
{
    const Metrics m = baseMetrics();
    const MarginsF normal = frameBorders(m, BorderPreset::Normal, false);
    CHECK_RECT(titleBarRect(m, 400.0, normal, false), 4.0, kTopResizeStrip, 392.0, 32.0);

    const MarginsF none = frameBorders(m, BorderPreset::None, false);
    CHECK_RECT(titleBarRect(m, 400.0, none, false), 1.0, 4.0, 398.0, 32.0);

    Metrics tall = m;
    tall.titleBarHeight = 64.0;
    CHECK_RECT(titleBarRect(tall, 400.0, frameBorders(tall, BorderPreset::Normal, false), false), 4.0, 4.0, 392.0, 60.0);
    Metrics shortBar = m;
    shortBar.titleBarHeight = 24.0;
    CHECK_RECT(titleBarRect(shortBar, 400.0, frameBorders(shortBar, BorderPreset::Normal, false), false), 4.0, 4.0, 392.0, 20.0);
}

/// Maximized title bar starts at the very top-left and spans the full width and bar height.
/// WHY: no resize strip is wanted on a maximized window, and the borders are 0 so x = 0.
static void testTitleBarRectMaximized()
{
    const Metrics m = baseMetrics();
    const MarginsF b = frameBorders(m, BorderPreset::Normal, true);
    CHECK_RECT(titleBarRect(m, 1920.0, b, true), 0.0, 0.0, 1920.0, 36.0);
}

/// The width is clamped to >= 0 for a decoration narrower than the borders, never negative.
/// WHY: a negative width would be passed on to QRectF and make an "empty but weird" rect.
/// Boundary: W = 9 -> 1; W = 8 -> exactly 0; W = 5 and W = 0 -> clamped to 0.
static void testTitleBarRectNarrow()
{
    const Metrics m = baseMetrics();
    const MarginsF normal = frameBorders(m, BorderPreset::Normal, false);
    CHECK_NEAR(titleBarRect(m, 9.0, normal, false).width, 1.0, 1e-9);
    CHECK_NEAR(titleBarRect(m, 8.0, normal, false).width, 0.0, 1e-9);
    CHECK_NEAR(titleBarRect(m, 5.0, normal, false).width, 0.0, 1e-9);
    CHECK_NEAR(titleBarRect(m, 0.0, normal, false).width, 0.0, 1e-9);
    CHECK(titleBarRect(m, 0.0, normal, false).width >= 0.0);
    CHECK_NEAR(titleBarRect(m, 0.0, frameBorders(m, BorderPreset::Normal, true), true).width, 0.0, 1e-9);
}

// ---- Buttons ---------------------------------------------------------------------------

/// buttonGroupWidth(): count * d + (count - 1) * spacing, 0 for an empty group.
/// d 14, spacing 8: 1 -> 14, 2 -> 36, 3 -> 58. Spacing 0: 3 -> 42. WHY the empty case: the
/// naive formula gives -spacing for count 0.
static void testButtonGroupWidth()
{
    const Metrics m = baseMetrics();
    CHECK_NEAR(buttonGroupWidth(0, m), 0.0, 1e-9);
    CHECK_NEAR(buttonGroupWidth(1, m), 14.0, 1e-9);
    CHECK_NEAR(buttonGroupWidth(2, m), 36.0, 1e-9);
    CHECK_NEAR(buttonGroupWidth(3, m), 58.0, 1e-9);

    Metrics tight = m;
    tight.buttonSpacing = 0.0;
    CHECK_NEAR(buttonGroupWidth(0, tight), 0.0, 1e-9);
    CHECK_NEAR(buttonGroupWidth(3, tight), 42.0, 1e-9);
}

/// buttonGroupOrigin(): left x = inset; right x = W - inset - groupWidth; y =
/// floor((bar - disc) / 2) for both. Left: (12, 11). Right with W 400, group 58: 400 - 12 -
/// 58 = 330.
static void testButtonGroupOrigin()
{
    const Metrics m = baseMetrics();
    const PointF left = buttonGroupOrigin(GroupSide::Left, 400.0, 58.0, m);
    CHECK_NEAR(left.x, 12.0, 1e-9);
    CHECK_NEAR(left.y, 11.0, 1e-9);

    const PointF right = buttonGroupOrigin(GroupSide::Right, 400.0, 58.0, m);
    CHECK_NEAR(right.x, 330.0, 1e-9);
    CHECK_NEAR(right.y, 11.0, 1e-9);

    // The left origin does not depend on the width arguments.
    CHECK_NEAR(buttonGroupOrigin(GroupSide::Left, 999.0, 123.0, m).x, 12.0, 1e-9);

    // Empty right group: its origin sits exactly one inset from the right edge.
    CHECK_NEAR(buttonGroupOrigin(GroupSide::Right, 400.0, 0.0, m).x, 388.0, 1e-9);
}

/// Vertical centring with floor on odd differences and at the token limits.
/// bar 36 / disc 13 -> floor(11.5) = 11 (the example in the interface notes);
/// bar 37 / disc 14 -> floor(11.5) = 11; bar 36 / disc 12.5 -> floor(11.75) = 11;
/// bar 24 / disc 8 -> 8; bar 64 / disc 20 -> 22; bar 24 / disc 20 -> 2; bar 25 / disc 20 ->
/// floor(2.5) = 2. WHY: rounding instead of flooring would give 12 in the first case.
static void testButtonGroupOriginVerticalCentring()
{
    struct Row {
        double bar, disc, y;
    };
    const Row rows[] = {{36, 13, 11}, {37, 14, 11}, {36, 12.5, 11}, {24, 8, 8}, {64, 20, 22}, {24, 20, 2}, {25, 20, 2}};
    for (const Row &r : rows) {
        Metrics m = baseMetrics();
        m.titleBarHeight = r.bar;
        m.buttonDiameter = r.disc;
        CHECK_NEAR(buttonGroupOrigin(GroupSide::Left, 400.0, 50.0, m).y, r.y, 1e-9);
        CHECK_NEAR(buttonGroupOrigin(GroupSide::Right, 400.0, 50.0, m).y, r.y, 1e-9);
    }
}

/// buttonRects(): button i at {origin.x + i * (d + spacing), origin.y, d, d}.
/// Origin (12, 11), d 14, spacing 8 -> x = 12, 34, 56; all on y = 11; 14 x 14.
static void testButtonRects()
{
    const Metrics m = baseMetrics();
    const PointF origin{12.0, 11.0};
    const std::vector<RectF> rects = buttonRects(3, origin, m);
    CHECK_EQ(rects.size(), std::size_t{3});
    if (rects.size() == 3) {
        CHECK_RECT(rects[0], 12.0, 11.0, 14.0, 14.0);
        CHECK_RECT(rects[1], 34.0, 11.0, 14.0, 14.0);
        CHECK_RECT(rects[2], 56.0, 11.0, 14.0, 14.0);
    }
    const std::vector<RectF> one = buttonRects(1, origin, m);
    CHECK_EQ(one.size(), std::size_t{1});
    if (one.size() == 1) {
        CHECK_RECT(one[0], 12.0, 11.0, 14.0, 14.0);
    }
}

/// Empty group -> empty vector. WHY: decoration.cpp loops over the result; a stray element
/// would paint a ghost disc.
static void testButtonRectsEmpty()
{
    CHECK(buttonRects(0, PointF{12.0, 11.0}, baseMetrics()).empty());
}

/// Spacing 0 -> discs touch (x step == diameter) and gaps equal the spacing otherwise; the
/// span of the rectangles equals buttonGroupWidth(). WHY: ties the two functions together,
/// which the run-time code relies on.
static void testButtonRectsSpacingAndSpan()
{
    Metrics m = baseMetrics();
    m.buttonSpacing = 0.0;
    const std::vector<RectF> touching = buttonRects(3, PointF{0.0, 0.0}, m);
    CHECK_EQ(touching.size(), std::size_t{3});
    if (touching.size() == 3) {
        CHECK_NEAR(touching[1].x, touching[0].x + touching[0].width, 1e-9);
        CHECK_NEAR(touching[2].x, touching[1].x + touching[1].width, 1e-9);
    }

    m = baseMetrics();
    const std::vector<RectF> rects = buttonRects(3, PointF{12.0, 11.0}, m);
    CHECK_EQ(rects.size(), std::size_t{3});
    if (rects.size() == 3) {
        const double span = rects[2].x + rects[2].width - rects[0].x;
        CHECK_NEAR(span, buttonGroupWidth(3, m), 1e-9);
        CHECK_NEAR(rects[1].x - (rects[0].x + rects[0].width), m.buttonSpacing, 1e-9);
        CHECK_NEAR(rects[2].x - (rects[1].x + rects[1].width), m.buttonSpacing, 1e-9);
        CHECK_NEAR(rects[0].y, rects[1].y, 0.0);
        CHECK_NEAR(rects[1].y, rects[2].y, 0.0);
    }
}

/// Spacer handling: a Spacer is just another slot of one disc diameter (the header counts
/// Spacers in `count`), so a group {Close, Spacer, Maximize} has 3 slots, the Spacer slot is
/// the disc-sized rect at x = 34, the next button is not shifted (x = 56) and the width is
/// 58. WHY: layouts like "X_A" must keep their spacing; the geometry layer must not
/// special-case or drop the slot.
static void testSpacerSlotKeepsSpacing()
{
    const Metrics m = baseMetrics();
    const std::vector<RectF> rects = buttonRects(3, PointF{12.0, 11.0}, m);
    CHECK_EQ(rects.size(), std::size_t{3});
    if (rects.size() == 3) {
        CHECK_RECT(rects[1], 34.0, 11.0, 14.0, 14.0); // the Spacer slot
        CHECK_NEAR(rects[2].x, 56.0, 1e-9);           // the button after it is not shifted
    }
    CHECK_NEAR(buttonGroupWidth(3, m), 58.0, 1e-9);
}

/// Pixel snapping: with integer metrics every rectangle edge is an integer (no half-pixel
/// positions), also for the odd-difference centring case (bar 36 / disc 13). WHY: the
/// header promises floor() centring "with the QML theme's rounding" for crisp discs.
static void testButtonRectsPixelAligned()
{
    Metrics m = baseMetrics();
    m.buttonDiameter = 13.0; // odd difference: (36 - 13) / 2 = 11.5 must be floored
    const double groupW = buttonGroupWidth(3, m);
    const PointF origin = buttonGroupOrigin(GroupSide::Left, 400.0, groupW, m);
    for (const RectF &r : buttonRects(3, origin, m)) {
        CHECK_NEAR(r.x, std::floor(r.x), 0.0);
        CHECK_NEAR(r.y, std::floor(r.y), 0.0);
        CHECK_NEAR(r.width, std::floor(r.width), 0.0);
        CHECK_NEAR(r.height, std::floor(r.height), 0.0);
    }
    const PointF rightOrigin = buttonGroupOrigin(GroupSide::Right, 401.0, groupW, m);
    CHECK_NEAR(rightOrigin.x, std::floor(rightOrigin.x), 0.0);
    CHECK_NEAR(rightOrigin.y, std::floor(rightOrigin.y), 0.0);
}

/// XIA on the left, end to end: the three discs of the left group in a 400 wide floating
/// window sit at x = 12, 34, 56, y = 11 (centred in the 36 high bar: 11 + 14 + 11 = 36).
static void testLeftGroupEndToEnd()
{
    const Metrics m = baseMetrics();
    const double groupW = buttonGroupWidth(3, m);
    const PointF origin = buttonGroupOrigin(GroupSide::Left, 400.0, groupW, m);
    const std::vector<RectF> rects = buttonRects(3, origin, m);
    CHECK_EQ(rects.size(), std::size_t{3});
    if (rects.size() == 3) {
        CHECK_NEAR(rects[0].x, 12.0, 1e-9);
        CHECK_NEAR(rects[1].x, 34.0, 1e-9);
        CHECK_NEAR(rects[2].x, 56.0, 1e-9);
        for (const RectF &r : rects) {
            CHECK_NEAR(r.y, 11.0, 1e-9);
            CHECK_NEAR(r.y + r.height + r.y, m.titleBarHeight, 1e-9); // equal margin above and below
        }
    }
}

// ---- Hover zone ------------------------------------------------------------------------

/// hoverZone(): {group.x - 4, 0, group.width + 8, titleBarHeight}. Group {12, 11, 58, 14}
/// -> {8, 0, 66, 36}: slack on both sides, full bar height (not the group's own height).
static void testHoverZone()
{
    const Metrics m = baseMetrics();
    const RectF zone = hoverZone(RectF{12.0, 11.0, 58.0, 14.0}, m);
    CHECK_RECT(zone, 8.0, 0.0, 66.0, 36.0);

    // Boundaries through contains(): x in [8, 74), y in [0, 36).
    CHECK(contains(zone, PointF{8.0, 0.0}));
    CHECK(!contains(zone, PointF{7.999, 10.0}));
    CHECK(contains(zone, PointF{73.999, 35.999}));
    CHECK(!contains(zone, PointF{74.0, 10.0}));
    CHECK(!contains(zone, PointF{30.0, 36.0}));
}

/// A group touching the frame edge gives a negative zone x (the slack is not clamped), and
/// the height follows the metrics. WHY: documents that clamping is the caller's business.
static void testHoverZoneNearEdgeAndHeight()
{
    Metrics m = baseMetrics();
    m.titleBarHeight = 64.0;
    CHECK_RECT(hoverZone(RectF{2.0, 11.0, 58.0, 14.0}, m), -2.0, 0.0, 66.0, 64.0);
}

/// An empty group gives an empty zone (zero width, zero height, or negative size).
/// WHY: a group with no buttons must never turn on the glyphs for a stray pointer.
static void testHoverZoneEmptyGroup()
{
    const Metrics m = baseMetrics();
    CHECK(isEmpty(hoverZone(RectF{}, m)));
    CHECK(isEmpty(hoverZone(RectF{12.0, 11.0, 0.0, 14.0}, m)));
    CHECK(isEmpty(hoverZone(RectF{12.0, 11.0, 58.0, 0.0}, m)));
    CHECK(isEmpty(hoverZone(RectF{12.0, 11.0, -5.0, 14.0}, m)));
}

// ---- Caption ---------------------------------------------------------------------------

/// captionRect(): pad = inset + max(left, right) + gap; result {pad, 0, max(0, W - 2 pad),
/// bar}. W 400, left 58, right 0, inset 12, gap 12 -> pad 82 -> {82, 0, 236, 36}. WHY
/// symmetric: the caption is centred in the WHOLE bar, so a one-sided group pads both sides.
static void testCaptionRectSymmetricPadding()
{
    const Metrics m = baseMetrics();
    CHECK_RECT(captionRect(400.0, 58.0, 0.0, m), 82.0, 0.0, 236.0, 36.0);
    CHECK_RECT(captionRect(400.0, 0.0, 58.0, m), 82.0, 0.0, 236.0, 36.0); // mirrored
    CHECK_RECT(captionRect(400.0, 58.0, 36.0, m), 82.0, 0.0, 236.0, 36.0); // max, not sum
    CHECK_RECT(captionRect(400.0, 36.0, 58.0, m), 82.0, 0.0, 236.0, 36.0);
    CHECK_RECT(captionRect(400.0, 0.0, 0.0, m), 24.0, 0.0, 352.0, 36.0); // pad = 12 + 0 + 12
}

/// The caption is centred across the whole bar: x + width / 2 == W / 2 whenever the width is
/// positive, for several widths and group combinations.
static void testCaptionRectCentred()
{
    const Metrics m = baseMetrics();
    for (const double w : {300.0, 400.0, 801.0}) {
        for (const double l : {0.0, 36.0, 58.0}) {
            for (const double r : {0.0, 14.0, 58.0}) {
                const RectF c = captionRect(w, l, r, m);
                if (c.width > 0.0) {
                    CHECK_NEAR(c.x + c.width / 2.0, w / 2.0, 1e-9);
                }
            }
        }
    }
}

/// Narrow window: the width clamps to 0 (never negative); boundary W == 2 pad gives 0 and
/// W == 2 pad + 1 gives 1. pad = 82 -> 164 / 165. Height is always the bar height.
static void testCaptionRectNarrowClamp()
{
    const Metrics m = baseMetrics();
    CHECK_NEAR(captionRect(165.0, 58.0, 0.0, m).width, 1.0, 1e-9);
    CHECK_NEAR(captionRect(164.0, 58.0, 0.0, m).width, 0.0, 1e-9);
    CHECK_NEAR(captionRect(100.0, 58.0, 0.0, m).width, 0.0, 1e-9);
    CHECK_NEAR(captionRect(0.0, 58.0, 0.0, m).width, 0.0, 1e-9);
    CHECK(captionRect(10.0, 58.0, 58.0, m).width >= 0.0);
    CHECK_NEAR(captionRect(100.0, 58.0, 0.0, m).height, 36.0, 1e-9);
    CHECK_NEAR(captionRect(100.0, 58.0, 0.0, m).y, 0.0, 1e-9);
}

// ---- Corner radius, snapping, outline --------------------------------------------------

/// cornerRadius(): 0 when maximized, m.cornerRadius otherwise (also a zero radius stays 0).
static void testCornerRadius()
{
    Metrics m = baseMetrics();
    CHECK_NEAR(cornerRadius(m, false), 14.0, 1e-9);
    CHECK_NEAR(cornerRadius(m, true), 0.0, 1e-9);
    m.cornerRadius = 0.0;
    CHECK_NEAR(cornerRadius(m, false), 0.0, 1e-9);
    m.cornerRadius = 20.0;
    CHECK_NEAR(cornerRadius(m, false), 20.0, 1e-9);
    CHECK_NEAR(cornerRadius(m, true), 0.0, 1e-9);
}

/// snapToPixelGrid(): round(value * scale) / scale with C `round` (halves away from zero).
/// Hand values: scale 1: 1.4 -> 1, 1.5 -> 2, 2.5 -> 3, -1.5 -> -2. Scale 1.25: 1 -> round(1.25)
/// = 1 -> 0.8; 4 -> round(5) = 5 -> 4; 3 -> round(3.75) = 4 -> 3.2. Scale 1.5: 1 -> round(1.5)
/// = 2 -> 1.3333...; 4 -> 6 / 1.5 = 4. Scale 2: 1.3 -> round(2.6) = 3 -> 1.5; 0.2 -> round(0.4)
/// = 0 -> 0. (Equality with KDecoration3::snapToPixelGrid is not checked here: this test has
/// no Qt dependency; the formula is identical by the header's contract.)
static void testSnapToPixelGrid()
{
    CHECK_NEAR(snapToPixelGrid(1.4, 1.0), 1.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(1.5, 1.0), 2.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(2.5, 1.0), 3.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(-1.5, 1.0), -2.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(0.0, 1.0), 0.0, 1e-12);

    CHECK_NEAR(snapToPixelGrid(1.0, 1.25), 0.8, 1e-12);
    CHECK_NEAR(snapToPixelGrid(4.0, 1.25), 4.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(3.0, 1.25), 3.2, 1e-12);

    CHECK_NEAR(snapToPixelGrid(1.0, 1.5), 4.0 / 3.0, 1e-12);
    CHECK_NEAR(snapToPixelGrid(4.0, 1.5), 4.0, 1e-12);

    CHECK_NEAR(snapToPixelGrid(1.3, 2.0), 1.5, 1e-12);
    CHECK_NEAR(snapToPixelGrid(0.2, 2.0), 0.0, 1e-12);
}

/// A scale that is not finite or <= 0 is treated as 1. WHY: nextScale() is documented to be
/// positive, but a bad value must not divide by zero or return NaN/inf into the layout.
static void testSnapToPixelGridInvalidScale()
{
    for (const double s : {0.0, -1.0, -2.5, kNaN, kInf, -kInf}) {
        CHECK_NEAR(snapToPixelGrid(2.6, s), 3.0, 1e-12);
        CHECK_NEAR(snapToPixelGrid(1.4, s), 1.0, 1e-12);
        CHECK(std::isfinite(snapToPixelGrid(2.6, s)));
    }
}

/// outlineThickness(): max(1 / scale, snapToPixelGrid(hairline, scale)). Hand values:
/// hairline 1: scale 1 -> 1; scale 2 -> max(0.5, 1) = 1; scale 1.5 -> max(0.6667, round(1.5)=2
/// / 1.5 = 1.3333) = 1.3333; scale 1.25 -> max(0.8, round(1.25)=1 / 1.25 = 0.8) = 0.8. Hairline
/// 0.1 snaps to 0 so the 1 / scale floor wins: scale 1 -> 1, scale 2 -> 0.5. Scale 0 / NaN /
/// negative behave like 1.
static void testOutlineThickness()
{
    Metrics m = baseMetrics();
    m.hairline = 1.0;
    CHECK_NEAR(outlineThickness(m, 1.0), 1.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, 2.0), 1.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, 1.5), 4.0 / 3.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, 1.25), 0.8, 1e-12);

    m.hairline = 0.1;
    CHECK_NEAR(outlineThickness(m, 1.0), 1.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, 2.0), 0.5, 1e-12);
    CHECK_NEAR(outlineThickness(m, 0.0), 1.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, kNaN), 1.0, 1e-12);
    CHECK_NEAR(outlineThickness(m, -3.0), 1.0, 1e-12);
}

/// The outline is never thinner than one device pixel (>= 1 / scale) and always > 0, over a
/// sweep of valid hairlines and scales. WHY: this is the stated purpose of the rule (the
/// hairline "never vanishes below one device pixel").
static void testOutlineThicknessNeverBelowOneDevicePixel()
{
    for (const double hairline : {0.01, 0.1, 0.3, 0.5, 1.0, 1.5, 3.0}) {
        for (const double scale : {1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0}) {
            Metrics m = baseMetrics();
            m.hairline = hairline;
            const double t = outlineThickness(m, scale);
            CHECK(t > 0.0);
            CHECK(t >= 1.0 / scale - 1e-12);
        }
    }
}

// ---- Glyphs ----------------------------------------------------------------------------

/// Helper: is there a bar with the given angle among the bars?
static bool hasBarWithAngle(const std::vector<GlyphBar> &bars, double angle)
{
    for (const GlyphBar &b : bars) {
        if (std::fabs(b.angleDegrees - angle) < 1e-9) {
            return true;
        }
    }
    return false;
}

/// glyphBars(Close): two bars, +45 and -45 degrees (order unspecified), both centred on the
/// disc, length 0.42 * d + stroke, thickness = stroke. Disc {20, 10, 14, 14}, stroke 1.5:
/// centre (27, 17), length 0.42 * 14 + 1.5 = 7.38.
static void testGlyphBarsClose()
{
    const RectF disc{20.0, 10.0, 14.0, 14.0};
    const std::vector<GlyphBar> bars = glyphBars(Glyph::Close, disc, 1.5);
    CHECK_EQ(bars.size(), std::size_t{2});
    CHECK(hasBarWithAngle(bars, 45.0));
    CHECK(hasBarWithAngle(bars, -45.0));
    for (const GlyphBar &b : bars) {
        CHECK_NEAR(b.centre.x, 27.0, 1e-9);
        CHECK_NEAR(b.centre.y, 17.0, 1e-9);
        CHECK_NEAR(b.length, 0.42 * 14.0 + 1.5, 1e-9);
        CHECK_NEAR(b.thickness, 1.5, 1e-9);
    }

    // The length scales with the disc and adds the stroke: disc 20, stroke 3 -> 8.4 + 3.
    const std::vector<GlyphBar> big = glyphBars(Glyph::Close, RectF{0.0, 0.0, 20.0, 20.0}, 3.0);
    CHECK_EQ(big.size(), std::size_t{2});
    for (const GlyphBar &b : big) {
        CHECK_NEAR(b.length, 0.42 * 20.0 + 3.0, 1e-9);
        CHECK_NEAR(b.thickness, 3.0, 1e-9);
        CHECK_NEAR(b.centre.x, 10.0, 1e-9);
        CHECK_NEAR(b.centre.y, 10.0, 1e-9);
    }
}

/// glyphBars(Minimize): one horizontal bar of length 0.35 * d + stroke. Disc {20, 10, 14,
/// 14}, stroke 1.5: centre (27, 17), length 4.9 + 1.5 = 6.4, angle 0.
static void testGlyphBarsMinimize()
{
    const std::vector<GlyphBar> bars = glyphBars(Glyph::Minimize, RectF{20.0, 10.0, 14.0, 14.0}, 1.5);
    CHECK_EQ(bars.size(), std::size_t{1});
    if (bars.size() == 1) {
        CHECK_NEAR(bars[0].centre.x, 27.0, 1e-9);
        CHECK_NEAR(bars[0].centre.y, 17.0, 1e-9);
        CHECK_NEAR(bars[0].length, 0.35 * 14.0 + 1.5, 1e-9);
        CHECK_NEAR(bars[0].thickness, 1.5, 1e-9);
        CHECK_NEAR(bars[0].angleDegrees, 0.0, 1e-9);
    }
}

/// Glyphs that are not drawn with bars (None, Maximize, Restore) produce no bars.
static void testGlyphBarsNone()
{
    const RectF disc{0.0, 0.0, 14.0, 14.0};
    CHECK(glyphBars(Glyph::None, disc, 1.5).empty());
    CHECK(glyphBars(Glyph::Maximize, disc, 1.5).empty());
    CHECK(glyphBars(Glyph::Restore, disc, 1.5).empty());
}

/// glyphTriangles(Maximize/Restore): each grid point p maps to disc.x + p.x * disc.width /
/// 12 (same for y). Disc 12 at the origin -> the grid values unchanged; disc 24 -> doubled;
/// disc {5, 7, 24, 24} -> x = 5 + 2 p.x, y = 7 + 2 p.y. The triangle order and the point order
/// follow the header's constants. Also pins a few literal grid values of the locked design
/// data so the mapping is not compared against a constant that was itself changed.
static void testGlyphTriangles()
{
    CHECK_NEAR(kMaximizeTriangles[0][0].x, 8.6, 1e-12);
    CHECK_NEAR(kMaximizeTriangles[0][0].y, 3.4, 1e-12);
    CHECK_NEAR(kMaximizeTriangles[1][2].x, 7.1, 1e-12);
    CHECK_NEAR(kMaximizeTriangles[1][2].y, 8.6, 1e-12);
    CHECK_NEAR(kRestoreTriangles[0][0].x, 7.3, 1e-12);
    CHECK_NEAR(kRestoreTriangles[0][0].y, 2.7, 1e-12);
    CHECK_NEAR(kRestoreTriangles[1][2].x, 6.7, 1e-12);
    CHECK_NEAR(kRestoreTriangles[1][2].y, 7.3, 1e-12);

    struct Case {
        Glyph glyph;
        const std::array<GridTriangle, 2> *grid;
    };
    const Case cases[] = {{Glyph::Maximize, &kMaximizeTriangles}, {Glyph::Restore, &kRestoreTriangles}};
    const RectF discs[] = {RectF{0.0, 0.0, 12.0, 12.0}, RectF{5.0, 7.0, 24.0, 24.0}, RectF{30.0, 10.0, 14.0, 14.0}};
    for (const Case &c : cases) {
        for (const RectF &disc : discs) {
            const std::vector<GridTriangle> tris = glyphTriangles(c.glyph, disc);
            CHECK_EQ(tris.size(), std::size_t{2});
            if (tris.size() != 2) {
                continue;
            }
            for (std::size_t t = 0; t < 2; ++t) {
                for (std::size_t i = 0; i < 3; ++i) {
                    const PointF &g = (*c.grid)[t][i];
                    CHECK_NEAR(tris[t][i].x, disc.x + g.x * disc.width / kGlyphGrid, 1e-9);
                    CHECK_NEAR(tris[t][i].y, disc.y + g.y * disc.height / kGlyphGrid, 1e-9);
                }
            }
        }
    }

    // Disc 12 at the origin: unchanged grid values (hand check of the first Maximize point).
    const std::vector<GridTriangle> unit = glyphTriangles(Glyph::Maximize, RectF{0.0, 0.0, 12.0, 12.0});
    CHECK_EQ(unit.size(), std::size_t{2});
    if (unit.size() == 2) {
        CHECK_NEAR(unit[0][0].x, 8.6, 1e-9);
        CHECK_NEAR(unit[0][0].y, 3.4, 1e-9);
    }
    // Disc 24 at the origin: doubled (8.6 -> 17.2, 3.4 -> 6.8).
    const std::vector<GridTriangle> dbl = glyphTriangles(Glyph::Maximize, RectF{0.0, 0.0, 24.0, 24.0});
    CHECK_EQ(dbl.size(), std::size_t{2});
    if (dbl.size() == 2) {
        CHECK_NEAR(dbl[0][0].x, 17.2, 1e-9);
        CHECK_NEAR(dbl[0][0].y, 6.8, 1e-9);
    }
}

/// Glyphs drawn with bars (None, Close, Minimize) produce no triangles.
static void testGlyphTrianglesNone()
{
    const RectF disc{0.0, 0.0, 14.0, 14.0};
    CHECK(glyphTriangles(Glyph::None, disc).empty());
    CHECK(glyphTriangles(Glyph::Close, disc).empty());
    CHECK(glyphTriangles(Glyph::Minimize, disc).empty());
}

int main()
{
    testDesignConstants();
    testTokenMetrics();
    testBaseMetricsValid();
    testIsValidRanges();
    testIsValidCornerRadius();
    testIsValidHairlineAndGap();
    testIsValidRejectsNonFinite();
    testIsEmpty();
    testContainsHalfOpen();
    testContainsEmptyRect();
    testFrameBorders();
    testResizeOnlyBorders();
    testTitleBarRect();
    testTitleBarRectMaximized();
    testTitleBarRectNarrow();
    testButtonGroupWidth();
    testButtonGroupOrigin();
    testButtonGroupOriginVerticalCentring();
    testButtonRects();
    testButtonRectsEmpty();
    testButtonRectsSpacingAndSpan();
    testSpacerSlotKeepsSpacing();
    testButtonRectsPixelAligned();
    testLeftGroupEndToEnd();
    testHoverZone();
    testHoverZoneNearEdgeAndHeight();
    testHoverZoneEmptyGroup();
    testCaptionRectSymmetricPadding();
    testCaptionRectCentred();
    testCaptionRectNarrowClamp();
    testCornerRadius();
    testSnapToPixelGrid();
    testSnapToPixelGridInvalidScale();
    testOutlineThickness();
    testOutlineThicknessNeverBelowOneDevicePixel();
    testGlyphBarsClose();
    testGlyphBarsMinimize();
    testGlyphBarsNone();
    testGlyphTriangles();
    testGlyphTrianglesNone();

    if (g_failures != 0) {
        std::cerr << g_failures << " of " << g_checks << " checks FAILED\n";
        return 1;
    }
    std::cout << g_checks << " checks passed\n";
    return 0;
}
