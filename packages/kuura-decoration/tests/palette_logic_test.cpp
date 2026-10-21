// Unit tests for src/palette_logic.h (pure colour logic of the Kuura window decoration).
//
// WHY these tests exist: they are written from the documented contract in palette_logic.h
// ONLY, before and independently of palette_logic.cpp. The colour state table (kind x
// active x hovered x pressed x enabled x mode) is walked exhaustively, and the colour maths
// (HSL lightness, QColor::darker semantics) is checked against values computed by hand in
// the comments, not against the implementation.
//
// BUILD ASSUMPTION: the CMake target adds the generated directory (generated/cpp) to the
// include path, as kuura-frost does; <token_colors.h> must provide
// Kuura::Tokens::Light / Kuura::Tokens::Dark constants kButtonClose, kButtonMinimize,
// kButtonMaximize, kTextDisabled, kSeparator, kShadow and kWindow (std::uint32_t, 0xRRGGBBAA)
// as specified in the comment block at the top of palette_logic.h. Where the contract says
// "from <token_colors.h>", the test compares with these constants, never with literals.
//
// Framework: plain C++20, no Qt, no external test library. main() returns non-zero on any
// failed check and prints every failure as file:line plus the compared values.

#include "palette_logic.h"

#include <token_colors.h>

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <type_traits>
#include <utility>

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

/// Render a colour as #RRGGBBAA-style decimal channels for failure messages.
std::string show(const Rgba &c)
{
    std::ostringstream os;
    os << "rgba(" << static_cast<int>(c.r) << "," << static_cast<int>(c.g) << "," << static_cast<int>(c.b) << "," << static_cast<int>(c.a) << ")";
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

/// Record a colour check: each of r, g, b within @p tol of the expected value, alpha exact.
void checkRgb(const Rgba &c, int r, int g, int b, int a, int tol, const char *expr, const char *file, int line)
{
    ++g_checks;
    const bool ok = std::abs(static_cast<int>(c.r) - r) <= tol && std::abs(static_cast<int>(c.g) - g) <= tol && std::abs(static_cast<int>(c.b) - b) <= tol
        && std::cmp_equal(c.a, a);
    if (!ok) {
        ++g_failures;
        std::cerr << file << ":" << line << ": CHECK_RGB failed: " << expr << " (got " << show(c) << ", expected rgba(" << r
                  << "," << g << "," << b << "," << a << ") +-" << tol << " on rgb)\n";
    }
}
} // namespace

#define CHECK(cond) check((cond), #cond, __FILE__, __LINE__)
#define CHECK_EQ(a, b) checkEq((a), (b), #a, #b, __FILE__, __LINE__)
#define CHECK_NEAR(a, b, eps) checkNear((a), (b), (eps), #a, #b, __FILE__, __LINE__)
#define CHECK_RGB(c, r, g, b, a, tol) checkRgb((c), (r), (g), (b), (a), (tol), #c, __FILE__, __LINE__)

// ---- Fixtures --------------------------------------------------------------------------

namespace
{
constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();

/// A palette with pairwise distinct colours, so a swapped field (close vs. minimize, idle vs.
/// separator, ...) changes the result. The three disc colours equal the shipped disc colours
/// only by coincidence of convenience: their darkened values are worked out by hand below.
ModePalette fixturePalette()
{
    ModePalette p;
    p.close = Rgba{229, 83, 75, 255};
    p.minimize = Rgba{217, 164, 65, 255};
    p.maximize = Rgba{79, 163, 107, 255};
    p.idle = Rgba{154, 163, 174, 255};
    p.separator = Rgba{213, 219, 227, 255};
    p.shadow = Rgba{0, 0, 0, 51};
    p.glyphInk = Rgba{21, 24, 28, 255};
    return p;
}

/// The colour a button of @p kind would have when drawn "active" (documented typeColour).
Rgba typeColour(ButtonKind kind, const ModePalette &p)
{
    switch (kind) {
    case ButtonKind::Close:
        return p.close;
    case ButtonKind::Minimize:
        return p.minimize;
    case ButtonKind::Maximize:
        return p.maximize;
    case ButtonKind::Spacer:
        break;
    }
    return Rgba{};
}

/// A state with only the given flags set; the rest keep their defaults except `enabled`,
/// which is passed explicitly.
ButtonVisualState makeState(bool active, bool groupHovered, bool hovered, bool pressed, bool enabled, bool maximized)
{
    ButtonVisualState s;
    s.windowActive = active;
    s.groupHovered = groupHovered;
    s.hovered = hovered;
    s.pressed = pressed;
    s.enabled = enabled;
    s.windowMaximized = maximized;
    return s;
}

constexpr ButtonKind kAllKinds[] = {ButtonKind::Close, ButtonKind::Minimize, ButtonKind::Maximize, ButtonKind::Spacer};
} // namespace

// ---- Constants -------------------------------------------------------------------------

/// Pins the documented tunables; the tests below hard-code 0.5 / 1.28 / 0.35 in hand values.
static void testConstants()
{
    CHECK_NEAR(kDarkLightnessThreshold, 0.5, 0.0);
    CHECK_NEAR(kPressedDarkerFactor, 1.28, 0.0);
    CHECK_NEAR(kDisabledOpacity, 0.35, 0.0);
    CHECK_NEAR(kGlyphOpacity, 0.78, 0.0);
}

// ---- unpackRgba / tokenPalette ---------------------------------------------------------

/// unpackRgba(): 0xRRGGBBAA, red in the most significant byte, alpha in the least. WHY a
/// distinct value per byte: any byte-order slip (ARGB, ABGR) changes the result.
static void testUnpackRgba()
{
    CHECK_RGB(unpackRgba(0x11223344u), 0x11, 0x22, 0x33, 0x44, 0);
    CHECK_RGB(unpackRgba(0xE5534BFFu), 0xE5, 0x53, 0x4B, 0xFF, 0);
    CHECK_RGB(unpackRgba(0x00000033u), 0, 0, 0, 0x33, 0);
    CHECK_RGB(unpackRgba(0x00000000u), 0, 0, 0, 0, 0);
    CHECK_RGB(unpackRgba(0xFFFFFFFFu), 255, 255, 255, 255, 0);
    CHECK_RGB(unpackRgba(0x80000001u), 0x80, 0, 0, 0x01, 0);
}

/// Rgba equality is member-wise (the tests rely on it): one differing channel is unequal.
static void testRgbaEquality()
{
    const Rgba base{1, 2, 3, 4};
    const Rgba same{1, 2, 3, 4};
    const Rgba diffR{9, 2, 3, 4};
    const Rgba diffG{1, 9, 3, 4};
    const Rgba diffB{1, 2, 9, 4};
    const Rgba diffA{1, 2, 3, 9};
    CHECK(base == same);
    CHECK(!(base == diffR));
    CHECK(!(base == diffG));
    CHECK(!(base == diffB));
    CHECK(!(base == diffA));
    CHECK(Rgba{}.a == 255); // default alpha is opaque
}

/// tokenPalette(): every field comes from the matching generated constant, per mode; the
/// glyph ink is color.dark.window in BOTH modes. WHY compare with the constants and not with
/// literals: the test then stays valid when tokens.json changes, and still catches a swapped
/// mode or a swapped field.
static void testTokenPalette()
{
    const ModePalette light = tokenPalette(Mode::Light);
    CHECK_EQ(light.close, unpackRgba(Kuura::Tokens::Light::kButtonClose));
    CHECK_EQ(light.minimize, unpackRgba(Kuura::Tokens::Light::kButtonMinimize));
    CHECK_EQ(light.maximize, unpackRgba(Kuura::Tokens::Light::kButtonMaximize));
    CHECK_EQ(light.idle, unpackRgba(Kuura::Tokens::Light::kTextDisabled));
    CHECK_EQ(light.separator, unpackRgba(Kuura::Tokens::Light::kSeparator));
    CHECK_EQ(light.shadow, unpackRgba(Kuura::Tokens::Light::kShadow));
    CHECK_EQ(light.glyphInk, unpackRgba(Kuura::Tokens::Dark::kWindow));

    const ModePalette dark = tokenPalette(Mode::Dark);
    CHECK_EQ(dark.close, unpackRgba(Kuura::Tokens::Dark::kButtonClose));
    CHECK_EQ(dark.minimize, unpackRgba(Kuura::Tokens::Dark::kButtonMinimize));
    CHECK_EQ(dark.maximize, unpackRgba(Kuura::Tokens::Dark::kButtonMaximize));
    CHECK_EQ(dark.idle, unpackRgba(Kuura::Tokens::Dark::kTextDisabled));
    CHECK_EQ(dark.separator, unpackRgba(Kuura::Tokens::Dark::kSeparator));
    CHECK_EQ(dark.shadow, unpackRgba(Kuura::Tokens::Dark::kShadow));
    CHECK_EQ(dark.glyphInk, unpackRgba(Kuura::Tokens::Dark::kWindow));

    // Both modes share one glyph ink (a near-black ink on the saturated discs).
    CHECK_EQ(light.glyphInk, dark.glyphInk);
}

// ---- hslLightness / modeForBackground --------------------------------------------------

/// hslLightness(): (max + min) / 2 on channels scaled to 0..1, alpha ignored. Hand values:
/// black 0, white 1, pure red/green/blue (255 + 0) / 2 / 255 = 0.5, yellow (255,255,0) 0.5,
/// grey 128 -> 128 / 255 = 0.50196, (200,100,50) -> (200 + 50) / 2 / 255 = 125 / 255,
/// (242,244,247) -> (247 + 242) / 2 / 255 = 244.5 / 255. WHY the pure colours: a luminance
/// or average formula would give 0.30 / 0.59 / 0.11 or 0.33 here instead of 0.5.
static void testHslLightness()
{
    CHECK_NEAR(hslLightness(Rgba{0, 0, 0, 255}), 0.0, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{255, 255, 255, 255}), 1.0, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{255, 0, 0, 255}), 0.5, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{0, 255, 0, 255}), 0.5, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{0, 0, 255, 255}), 0.5, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{255, 255, 0, 255}), 0.5, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{128, 128, 128, 255}), 128.0 / 255.0, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{200, 100, 50, 255}), 125.0 / 255.0, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{242, 244, 247, 255}), 244.5 / 255.0, 1e-9);
    // Alpha is ignored.
    CHECK_NEAR(hslLightness(Rgba{200, 100, 50, 0}), 125.0 / 255.0, 1e-9);
    CHECK_NEAR(hslLightness(Rgba{10, 10, 10, 7}), 10.0 / 255.0, 1e-9);
}

/// modeForBackground(): Dark iff hslLightness < 0.5. Grey 127 -> 0.498 -> Dark, grey 128 ->
/// 0.50196 -> Light (just below / above). Pure red has lightness exactly 0.5 -> not below ->
/// Light; (254,0,0) -> 0.498 -> Dark. WHY: pins the comparison operator at the threshold.
static void testModeForBackgroundThreshold()
{
    CHECK_EQ(modeForBackground(Rgba{127, 127, 127, 255}), Mode::Dark);
    CHECK_EQ(modeForBackground(Rgba{128, 128, 128, 255}), Mode::Light);
    CHECK_EQ(modeForBackground(Rgba{255, 0, 0, 255}), Mode::Light);
    CHECK_EQ(modeForBackground(Rgba{0, 0, 255, 255}), Mode::Light);
    CHECK_EQ(modeForBackground(Rgba{254, 0, 0, 255}), Mode::Dark);
    CHECK_EQ(modeForBackground(Rgba{0, 0, 0, 255}), Mode::Dark);
    CHECK_EQ(modeForBackground(Rgba{255, 255, 255, 255}), Mode::Light);
}

/// The two project window colours select their own mode, and alpha does not matter. WHY: this
/// is the production use (title bar = `window` token): light ~0.96 -> Light, dark ~0.09 ->
/// Dark.
static void testModeForBackgroundProjectColours()
{
    CHECK_EQ(modeForBackground(unpackRgba(Kuura::Tokens::Light::kWindow)), Mode::Light);
    CHECK_EQ(modeForBackground(unpackRgba(Kuura::Tokens::Dark::kWindow)), Mode::Dark);
    CHECK_EQ(modeForBackground(Rgba{255, 255, 255, 0}), Mode::Light);
    CHECK_EQ(modeForBackground(Rgba{0, 0, 0, 0}), Mode::Dark);
}

// ---- darker ----------------------------------------------------------------------------

/// darker(c, 1.28), computed by hand with QColor::darker(128) semantics. Qt converts to HSV,
/// divides V by factor and converts back with H, S, alpha kept. In HSV the RGB triple is
/// V * f(H, S), so changing V alone scales EVERY channel by the same ratio V' / V = 1 / 1.28 =
/// 0.78125. Hand values (tolerance +-1 step for Qt's integer HSV rounding):
///   close    (229,  83,  75) -> (178.9,  64.8,  58.6) -> (179,  65,  59)
///   minimize (217, 164,  65) -> (169.5, 128.1,  50.8) -> (170, 128,  51)
///   maximize ( 79, 163, 107) -> ( 61.7, 127.3,  83.6) -> ( 62, 127,  84)
///   white    (255, 255, 255) -> (199.2) -> (199, 199, 199)
/// Grey 128 with factor 2.0 -> 64; black stays black; pure red with factor 2 -> (127.5, 0, 0).
static void testDarkerHandValues()
{
    CHECK_RGB(darker(Rgba{229, 83, 75, 255}, 1.28), 179, 65, 59, 255, 1);
    CHECK_RGB(darker(Rgba{217, 164, 65, 255}, 1.28), 170, 128, 51, 255, 1);
    CHECK_RGB(darker(Rgba{79, 163, 107, 255}, 1.28), 62, 127, 84, 255, 1);
    CHECK_RGB(darker(Rgba{255, 255, 255, 255}, 1.28), 199, 199, 199, 255, 1);
    CHECK_RGB(darker(Rgba{128, 128, 128, 255}, 2.0), 64, 64, 64, 255, 1);
    CHECK_RGB(darker(Rgba{0, 0, 0, 255}, 1.28), 0, 0, 0, 255, 0);
    CHECK_RGB(darker(Rgba{255, 0, 0, 255}, 2.0), 128, 0, 0, 255, 1);
}

/// Alpha is preserved by darker() (Qt keeps it), also for translucent and fully transparent
/// colours. Factor 1.0 changes nothing (V / 1 = V), within one step.
static void testDarkerKeepsAlphaAndIdentity()
{
    CHECK_RGB(darker(Rgba{229, 83, 75, 77}, 1.28), 179, 65, 59, 77, 1);
    CHECK_RGB(darker(Rgba{229, 83, 75, 0}, 1.28), 179, 65, 59, 0, 1);
    CHECK_RGB(darker(Rgba{229, 83, 75, 255}, 1.0), 229, 83, 75, 255, 1);
}

/// A factor <= 0 or not finite returns the input unchanged (documented deviation from Qt,
/// which returns an invalid colour). WHY: painting with an invalid colour is worse than not
/// darkening. Boundary: factor 0, negative, NaN, +inf, -inf all unchanged.
static void testDarkerInvalidFactor()
{
    const Rgba c{229, 83, 75, 200};
    for (const double f : {0.0, -1.0, -0.001, kNaN, kInf, -kInf}) {
        CHECK_EQ(darker(c, f), c);
    }
}

/// Factors below 1 lighten as in Qt (QColor::darker(50) == lighter(200)): V doubles when it
/// does not clip. (100,50,25) with factor 0.5 -> (200,100,50). A larger factor is never
/// lighter than a smaller one (monotonic), sampled on one colour.
static void testDarkerLightensAndIsMonotonic()
{
    CHECK_RGB(darker(Rgba{100, 50, 25, 255}, 0.5), 200, 100, 50, 255, 1);

    const Rgba c{200, 120, 60, 255};
    int previous = 1000;
    for (const double f : {0.8, 1.0, 1.28, 1.5, 2.0, 4.0, 10.0}) {
        const Rgba d = darker(c, f);
        CHECK(std::cmp_less_equal(d.r, previous));
        previous = static_cast<int>(d.r);
    }
    // Strictly darker for a real darkening factor.
    CHECK(darker(c, 1.28).r < c.r);
    CHECK(darker(c, 1.28).g < c.g);
    CHECK(darker(c, 1.28).b < c.b);
}

// ---- discColor -------------------------------------------------------------------------

/// discColor() over the whole state table: kind x windowActive x groupHovered x hovered x
/// pressed x enabled x windowMaximized, for the fixture palette and both shipped token
/// palettes. Rule: pressed -> darker(type, 1.28); else active || groupHovered -> type; else
/// idle. `hovered` alone, `enabled` and `windowMaximized` do not change the colour (opacity
/// handles disabled). Spacer -> no value for every combination.
static void testDiscColorTable()
{
    const ModePalette palettes[] = {fixturePalette(), tokenPalette(Mode::Light), tokenPalette(Mode::Dark)};
    for (const ModePalette &palette : palettes) {
        for (const ButtonKind kind : kAllKinds) {
            for (int bits = 0; bits < 64; ++bits) {
                const bool active = bits & 1;
                const bool groupHovered = bits & 2;
                const bool hovered = bits & 4;
                const bool pressed = bits & 8;
                const bool enabled = bits & 16;
                const bool maximized = bits & 32;
                const ButtonVisualState s = makeState(active, groupHovered, hovered, pressed, enabled, maximized);
                const std::optional<Rgba> got = discColor(kind, s, palette);

                if (kind == ButtonKind::Spacer) {
                    CHECK(!got.has_value());
                    continue;
                }
                CHECK(got.has_value());
                if (!got.has_value()) {
                    continue;
                }
                const Rgba type = typeColour(kind, palette);
                if (pressed) {
                    CHECK_EQ(*got, darker(type, kPressedDarkerFactor));
                } else if (active || groupHovered) {
                    CHECK_EQ(*got, type);
                } else {
                    CHECK_EQ(*got, palette.idle);
                }
            }
        }
    }
}

/// Named scenarios with hand-computed colours on the fixture palette (so the table above
/// cannot be satisfied by an implementation that merely mirrors the same wrong rule).
/// - active window, nothing else: the type colour.
/// - inactive window, no hover: neutral idle grey (attention goes to the focused window).
/// - inactive window, group hovered: colours come back.
/// - pressed wins over idle: an inactive, unhovered pressed button is the DARKENED type
///   colour, not the idle grey. Close pressed: (179,65,59) +-1 (see testDarkerHandValues).
static void testDiscColorScenarios()
{
    const ModePalette p = fixturePalette();

    const std::optional<Rgba> active = discColor(ButtonKind::Close, makeState(true, false, false, false, true, false), p);
    CHECK(active.has_value());
    if (active) {
        CHECK_RGB(*active, 229, 83, 75, 255, 0);
    }

    const std::optional<Rgba> idle = discColor(ButtonKind::Minimize, makeState(false, false, false, false, true, false), p);
    CHECK(idle.has_value());
    if (idle) {
        CHECK_RGB(*idle, 154, 163, 174, 255, 0);
    }

    const std::optional<Rgba> hover = discColor(ButtonKind::Maximize, makeState(false, true, false, false, true, false), p);
    CHECK(hover.has_value());
    if (hover) {
        CHECK_RGB(*hover, 79, 163, 107, 255, 0);
    }

    const std::optional<Rgba> pressedIdle = discColor(ButtonKind::Close, makeState(false, false, false, true, true, false), p);
    CHECK(pressedIdle.has_value());
    if (pressedIdle) {
        CHECK_RGB(*pressedIdle, 179, 65, 59, 255, 1);
        CHECK(!(*pressedIdle == p.idle));
    }

    // The three kinds use three different fields (a swap would be caught here).
    const ButtonVisualState a = makeState(true, false, false, false, true, false);
    const std::optional<Rgba> closeColor = discColor(ButtonKind::Close, a, p);
    const std::optional<Rgba> minimizeColor = discColor(ButtonKind::Minimize, a, p);
    const std::optional<Rgba> maximizeColor = discColor(ButtonKind::Maximize, a, p);
    CHECK(closeColor.has_value() && minimizeColor.has_value() && maximizeColor.has_value());
    if (closeColor && minimizeColor && maximizeColor) {
        CHECK(!(*closeColor == *minimizeColor));
        CHECK(!(*minimizeColor == *maximizeColor));
        CHECK(!(*closeColor == *maximizeColor));
    }
}

// ---- buttonOpacity / showGlyph / glyphFor ----------------------------------------------

/// buttonOpacity(): 1.0 when enabled, kDisabledOpacity (0.35) when not, independent of every
/// other flag. WHY the sweep: a disabled but pressed or hovered button must still be dimmed.
static void testButtonOpacity()
{
    for (int bits = 0; bits < 32; ++bits) {
        const bool active = bits & 1;
        const bool groupHovered = bits & 2;
        const bool hovered = bits & 4;
        const bool pressed = bits & 8;
        const bool maximized = bits & 16;
        CHECK_NEAR(buttonOpacity(makeState(active, groupHovered, hovered, pressed, true, maximized)), 1.0, 1e-12);
        CHECK_NEAR(buttonOpacity(makeState(active, groupHovered, hovered, pressed, false, maximized)), 0.35, 1e-12);
    }
}

/// showGlyph(): groupHovered || hovered || pressed, nothing else (not the active flag, not
/// enabled, not maximized). All 8 combinations of the three flags, each with the other flags
/// both off and on.
static void testShowGlyph()
{
    for (int bits = 0; bits < 8; ++bits) {
        const bool groupHovered = bits & 1;
        const bool hovered = bits & 2;
        const bool pressed = bits & 4;
        const bool expected = groupHovered || hovered || pressed;
        for (const bool other : {false, true}) {
            CHECK_EQ(showGlyph(makeState(other, groupHovered, hovered, pressed, !other, other)), expected);
        }
    }
}

/// glyphFor(): None unless the glyph is shown; Spacer always None; Close -> Close; Minimize ->
/// Minimize; Maximize -> Restore when the window is maximized, else Maximize. Walks the whole
/// table. WHY: the restore glyph must replace the maximize glyph only for the Maximize kind
/// and only while maximized.
static void testGlyphFor()
{
    for (const ButtonKind kind : kAllKinds) {
        for (int bits = 0; bits < 32; ++bits) {
            const bool groupHovered = bits & 1;
            const bool hovered = bits & 2;
            const bool pressed = bits & 4;
            const bool maximized = bits & 8;
            const bool enabled = bits & 16;
            const ButtonVisualState s = makeState(true, groupHovered, hovered, pressed, enabled, maximized);

            Glyph expected = Glyph::None;
            if (showGlyph(s) && kind != ButtonKind::Spacer) {
                switch (kind) {
                case ButtonKind::Close:
                    expected = Glyph::Close;
                    break;
                case ButtonKind::Minimize:
                    expected = Glyph::Minimize;
                    break;
                case ButtonKind::Maximize:
                    expected = maximized ? Glyph::Restore : Glyph::Maximize;
                    break;
                case ButtonKind::Spacer:
                    break;
                }
            }
            CHECK_EQ(glyphFor(kind, s), expected);
        }
    }

    // Explicit spot checks, independent of the loop above.
    CHECK_EQ(glyphFor(ButtonKind::Maximize, makeState(true, true, false, false, true, true)), Glyph::Restore);
    CHECK_EQ(glyphFor(ButtonKind::Maximize, makeState(true, true, false, false, true, false)), Glyph::Maximize);
    CHECK_EQ(glyphFor(ButtonKind::Close, makeState(true, true, false, false, true, true)), Glyph::Close);
    CHECK_EQ(glyphFor(ButtonKind::Minimize, makeState(true, false, true, false, true, true)), Glyph::Minimize);
    CHECK_EQ(glyphFor(ButtonKind::Close, makeState(true, false, false, false, true, false)), Glyph::None);
    CHECK_EQ(glyphFor(ButtonKind::Maximize, makeState(true, false, false, false, true, true)), Glyph::None);
    CHECK_EQ(glyphFor(ButtonKind::Spacer, makeState(true, true, true, true, true, true)), Glyph::None);
}

int main()
{
    testConstants();
    testUnpackRgba();
    testRgbaEquality();
    testTokenPalette();
    testHslLightness();
    testModeForBackgroundThreshold();
    testModeForBackgroundProjectColours();
    testDarkerHandValues();
    testDarkerKeepsAlphaAndIdentity();
    testDarkerInvalidFactor();
    testDarkerLightensAndIsMonotonic();
    testDiscColorTable();
    testDiscColorScenarios();
    testButtonOpacity();
    testShowGlyph();
    testGlyphFor();

    if (g_failures != 0) {
        std::cerr << g_failures << " of " << g_checks << " checks FAILED\n";
        return 1;
    }
    std::cout << g_checks << " checks passed\n";
    return 0;
}
