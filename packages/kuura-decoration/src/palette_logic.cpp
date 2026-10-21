// Implementation of palette_logic.h: light/dark choice, token palette and the per-state
// colours of the traffic-light buttons. Every public function is documented in the
// header; comments here explain only the non-obvious colour maths.

#include "palette_logic.h"

#include <token_colors.h>

#include <algorithm>
#include <cmath>

namespace Kuura::Deco
{

namespace
{

/// Convert a 0..1 channel back to 8 bits, rounding to nearest and clamping.
std::uint8_t toByte(double v)
{
    return static_cast<std::uint8_t>(std::clamp(std::lround(v * 255.0), 0L, 255L));
}

/// The colour of a button kind; Spacer has none.
std::optional<Rgba> typeColour(ButtonKind kind, const ModePalette &palette)
{
    switch (kind) {
    case ButtonKind::Close:
        return palette.close;
    case ButtonKind::Minimize:
        return palette.minimize;
    case ButtonKind::Maximize:
        return palette.maximize;
    case ButtonKind::Spacer:
        break;
    }
    return std::nullopt;
}

} // namespace

Rgba unpackRgba(std::uint32_t packed)
{
    return Rgba{.r = static_cast<std::uint8_t>((packed >> 24) & 0xFFu),
                .g = static_cast<std::uint8_t>((packed >> 16) & 0xFFu),
                .b = static_cast<std::uint8_t>((packed >> 8) & 0xFFu),
                .a = static_cast<std::uint8_t>(packed & 0xFFu)};
}

double hslLightness(const Rgba &c)
{
    const int hi = std::max({c.r, c.g, c.b});
    const int lo = std::min({c.r, c.g, c.b});
    return (static_cast<double>(hi) + static_cast<double>(lo)) / (2.0 * 255.0);
}

Mode modeForBackground(const Rgba &titleBar)
{
    return hslLightness(titleBar) < kDarkLightnessThreshold ? Mode::Dark : Mode::Light;
}

ModePalette tokenPalette(Mode mode)
{
    namespace L = Kuura::Tokens::Light;
    namespace D = Kuura::Tokens::Dark;
    const bool dark = mode == Mode::Dark;
    ModePalette p;
    p.close = unpackRgba(dark ? D::kButtonClose : L::kButtonClose);
    p.minimize = unpackRgba(dark ? D::kButtonMinimize : L::kButtonMinimize);
    p.maximize = unpackRgba(dark ? D::kButtonMaximize : L::kButtonMaximize);
    p.idle = unpackRgba(dark ? D::kTextDisabled : L::kTextDisabled);
    p.separator = unpackRgba(dark ? D::kSeparator : L::kSeparator);
    p.shadow = unpackRgba(dark ? D::kShadow : L::kShadow);
    // Dark window colour in BOTH modes: near-black ink on a saturated disc (header).
    p.glyphInk = unpackRgba(D::kWindow);
    return p;
}

Rgba darker(const Rgba &c, double factor)
{
    if (!std::isfinite(factor) || factor <= 0.0) {
        return c;
    }

    // RGB -> HSV on 0..1 channels.
    const double r = c.r / 255.0;
    const double g = c.g / 255.0;
    const double b = c.b / 255.0;
    const double hi = std::max({r, g, b});
    const double lo = std::min({r, g, b});
    const double delta = hi - lo;
    double v = hi;
    double s = hi > 0.0 ? delta / hi : 0.0;
    double h = 0.0; // degrees, irrelevant for greys (delta == 0)
    if (delta > 0.0) {
        if (hi == r) {
            h = 60.0 * std::fmod((g - b) / delta, 6.0);
        } else if (hi == g) {
            h = 60.0 * ((b - r) / delta + 2.0);
        } else {
            h = 60.0 * ((r - g) / delta + 4.0);
        }
        if (h < 0.0) {
            h += 360.0;
        }
    }

    // QColor::darker(): V / factor. A factor < 1 is QColor::lighter(): when V would exceed
    // the maximum, the overshoot is taken out of the saturation instead (the colour moves
    // towards white), exactly as Qt does in lighter().
    v /= factor;
    if (v > 1.0) {
        s = std::max(0.0, s - (v - 1.0));
        v = 1.0;
    }

    // HSV -> RGB (standard sector formula).
    const double chroma = v * s;
    const double hp = h / 60.0;
    const double x = chroma * (1.0 - std::fabs(std::fmod(hp, 2.0) - 1.0));
    double r1 = 0.0;
    double g1 = 0.0;
    double b1 = 0.0;
    if (hp < 1.0) {
        r1 = chroma; g1 = x;
    } else if (hp < 2.0) {
        r1 = x; g1 = chroma;
    } else if (hp < 3.0) {
        g1 = chroma; b1 = x;
    } else if (hp < 4.0) {
        g1 = x; b1 = chroma;
    } else if (hp < 5.0) {
        r1 = x; b1 = chroma;
    } else {
        r1 = chroma; b1 = x;
    }
    const double m = v - chroma;
    return Rgba{.r = toByte(r1 + m), .g = toByte(g1 + m), .b = toByte(b1 + m), .a = c.a};
}

std::optional<Rgba> discColor(ButtonKind kind, const ButtonVisualState &state, const ModePalette &palette)
{
    const std::optional<Rgba> type = typeColour(kind, palette);
    if (!type) {
        return std::nullopt;
    }
    // Pressed wins over everything so the click is always visible; otherwise an
    // unfocused window shows neutral discs until the pointer reaches the group.
    // `hovered` alone deliberately does not count (header rule): groupHovered covers it.
    if (state.pressed) {
        return darker(*type, kPressedDarkerFactor);
    }
    if (state.windowActive || state.groupHovered) {
        return type;
    }
    return palette.idle;
}

double buttonOpacity(const ButtonVisualState &state)
{
    return state.enabled ? 1.0 : kDisabledOpacity;
}

bool showGlyph(const ButtonVisualState &state)
{
    return state.groupHovered || state.hovered || state.pressed;
}

Glyph glyphFor(ButtonKind kind, const ButtonVisualState &state)
{
    if (!showGlyph(state)) {
        return Glyph::None;
    }
    switch (kind) {
    case ButtonKind::Close:
        return Glyph::Close;
    case ButtonKind::Minimize:
        return Glyph::Minimize;
    case ButtonKind::Maximize:
        return state.windowMaximized ? Glyph::Restore : Glyph::Maximize;
    case ButtonKind::Spacer:
        break;
    }
    return Glyph::None;
}

} // namespace Kuura::Deco
