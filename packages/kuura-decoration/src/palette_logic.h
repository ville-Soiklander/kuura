#pragma once

/**
 * @file palette_logic.h
 * @brief Pure colour logic of the decoration: light/dark choice, per-mode token palette,
 *        disc colour per button state, dimming and glyph visibility.
 *
 * LOCKED INTERFACE (phase 1). Declarations only; the definitions go into palette_logic.cpp.
 *
 * WHY Qt-free: like geometry.h, so the state table (type x active x hovered x pressed x
 * enabled x mode) can be unit-tested exhaustively without a compositor.
 *
 * WHERE THE COLOURS COME FROM (two sources, as in the QML theme):
 *  1. Title-bar background and caption colour come from the ACTIVE COLOUR SCHEME at run
 *     time: decoration.cpp reads DecoratedWindow::color(ColorGroup, ColorRole::TitleBar /
 *     ColorRole::Foreground) (kdecoration src/decoratedwindow.h). KWin fills those from the
 *     scheme's [Colors:Header] set when the scheme has one (ours does,
 *     design/generators/plasma_colors.py), otherwise from kdeglobals [WM]
 *     (kwin src/decorations/decorationpalette.cpp, DecorationPalette::update() and
 *     color()). KWin re-reads the scheme through a KConfigWatcher and emits
 *     Window::paletteChanged, which both repaints the decoration
 *     (kwin src/window.cpp: paletteChanged -> triggerDecorationRepaint) and is forwarded as
 *     DecoratedWindow::paletteChanged (kwin src/decorations/decoratedwindow.cpp). So a
 *     `plasma-apply-colorscheme` switch restyles open windows with no extra step.
 *  2. Disc, idle-disc, separator (outline), shadow and glyph-ink colours are PROJECT TOKENS
 *     that differ per mode. They come from a generated header (see the TODO block below)
 *     and are chosen by modeForBackground() from the scheme's title-bar colour.
 */

#include "geometry.h"

#include <cstdint>
#include <optional>

/*
 * TODO(design/, not part of this package): generated colour header.
 *
 * design/generators/cpp_header.py exports every token EXCEPT `color.*` (its docstring:
 * colour tokens are mode-dependent and render() takes no mode). This package needs the
 * per-mode colours as compile-time constants too, so the design/ owner must add:
 *
 *   - a new function `cpp_header.render_colors(tokens: dict) -> str` (render() and the
 *     existing cpp/tokens.h stay byte-identical, so packages/kuura-frost is unaffected);
 *   - design/generate.py writes its result to `<out-dir>/cpp/token_colors.h`;
 *   - exact output (LF, single trailing newline), one constant per leaf of
 *     tokens["color"]["light"] and tokens["color"]["dark"], sorted by constant name:
 *
 *       #pragma once
 *
 *       // Colour tokens - generated from design/tokens.json, do not edit by hand.
 *       // Each value is 0xRRGGBBAA; a "#RRGGBB" token gets AA = FF.
 *       #include <cstdint>
 *
 *       namespace Kuura::Tokens::Light
 *       {
 *       inline constexpr std::uint32_t kButtonClose = 0xE5534BFFu;
 *       ...
 *       } // namespace Kuura::Tokens::Light
 *
 *       namespace Kuura::Tokens::Dark
 *       {
 *       ...
 *       } // namespace Kuura::Tokens::Dark
 *
 *   - naming: "k" + PascalCase of the leaf key with "_" as separator (the same rule as
 *     cpp_header._to_pascal_case): button_close -> kButtonClose, text_disabled ->
 *     kTextDisabled, shadow -> kShadow (0x00000033u light, 0x00000066u dark).
 *   - hex digits uppercase, suffix "u", type std::uint32_t.
 *
 * This package uses: kButtonClose, kButtonMinimize, kButtonMaximize, kTextDisabled,
 * kSeparator, kShadow (both modes) and Dark::kWindow (glyph ink, see ModePalette).
 * Only palette_logic.cpp includes <token_colors.h>.
 */

namespace Kuura::Deco
{

/**
 * @brief An 8-bit-per-channel colour with straight (non-premultiplied) alpha.
 */
struct Rgba {
    std::uint8_t r = 0;
    std::uint8_t g = 0;
    std::uint8_t b = 0;
    std::uint8_t a = 255;

    /// Member-wise equality (used by the tests).
    bool operator==(const Rgba &other) const = default;
};

/**
 * @brief Light or dark project palette.
 */
enum class Mode {
    Light,
    Dark,
};

/// HSL lightness below which the title bar counts as dark (QML theme: `hslLightness < 0.5`).
/// WHY 0.5: the scheme's title-bar colour is the `window` token, about 0.96 lightness in the
/// light palette and 0.09 in the dark one, so 0.5 separates them with a wide margin and
/// degrades sensibly for a third-party scheme.
inline constexpr double kDarkLightnessThreshold = 0.5;
/// Factor of QColor::darker() applied to a pressed disc (QML `Qt.darker(color, 1.28)`).
inline constexpr double kPressedDarkerFactor = 1.28;
/// Opacity of a disabled button, e.g. maximize on a fixed-size window (QML `0.35`).
inline constexpr double kDisabledOpacity = 0.35;
/// Opacity of the glyph ink on the disc (aurorae.py `_GLYPH_OPACITY`).
inline constexpr double kGlyphOpacity = 0.78;

/**
 * @brief The project-token colours of one mode.
 */
struct ModePalette {
    Rgba close;     ///< color.<mode>.button_close.
    Rgba minimize;  ///< color.<mode>.button_minimize.
    Rgba maximize;  ///< color.<mode>.button_maximize.
    Rgba idle;      ///< color.<mode>.text_disabled: disc of an unfocused, unhovered window.
    Rgba separator; ///< color.<mode>.separator: the frame outline.
    Rgba shadow;    ///< color.<mode>.shadow: shadow colour; its alpha is the peak opacity.
    /// Glyph ink: color.dark.window in BOTH modes. WHY: the glyph sits on a saturated disc,
    /// where a near-black ink keeps its contrast in either mode (aurorae.py "INK").
    Rgba glyphInk;
};

/**
 * @brief Everything about one button and its window that decides how the button looks.
 *
 * Filled by Button::paint() from DecorationButton (isHovered(), isPressed(), isEnabled(),
 * isChecked()), DecoratedWindow::isActive() and Decoration::buttonsHovered() (decoration.h).
 */
struct ButtonVisualState {
    bool windowActive = false;    ///< DecoratedWindow::isActive().
    bool groupHovered = false;    ///< Pointer inside either hoverZone() (decoration-wide).
    bool hovered = false;         ///< DecorationButton::isHovered() of this button.
    bool pressed = false;         ///< DecorationButton::isPressed().
    bool enabled = true;          ///< DecorationButton::isEnabled() (closeable/minimizeable/
                                  ///< maximizeable, kdecoration src/decorationbutton.cpp).
    /// DecorationButton::isChecked() of the maximize button. KDecoration3 keeps it equal to
    /// DecoratedWindow::isMaximized() (decorationbutton.cpp, Maximize case: setChecked +
    /// connect maximizedChanged -> setChecked), so the button needs no own connection.
    bool windowMaximized = false;
};

/**
 * @brief Unpack a 0xRRGGBBAA constant from <token_colors.h>.
 * @param packed Colour as 0xRRGGBBAA.
 * @return The colour.
 */
Rgba unpackRgba(std::uint32_t packed);

/**
 * @brief HSL lightness, (max(r,g,b) + min(r,g,b)) / 2 on channels scaled to 0..1.
 *
 * WHY HSL and not luminance: it is what the QML theme used (`hslLightness`) and what
 * QColor::lightnessF() returns, so behaviour is unchanged; tests compare with QColor.
 *
 * @param c Colour (alpha ignored).
 * @return Lightness in 0..1.
 */
double hslLightness(const Rgba &c);

/**
 * @brief Choose the project palette for a title-bar colour.
 *
 * Dark if hslLightness(titleBar) < kDarkLightnessThreshold, else Light.
 *
 * WHY decoration.cpp passes the ACTIVE title-bar colour even for an inactive window: the
 * mode then cannot flip on focus changes if a scheme's inactive header colour sits on the
 * other side of the threshold. In the project schemes both are the `window` colour.
 *
 * @param titleBar Title-bar background from DecoratedWindow::color().
 * @return The mode.
 */
Mode modeForBackground(const Rgba &titleBar);

/**
 * @brief The token palette of a mode, from <token_colors.h>.
 * @param mode Light or Dark.
 * @return The palette. Never fails (compile-time constants).
 */
ModePalette tokenPalette(Mode mode);

/**
 * @brief Darken a colour with QColor::darker() semantics.
 *
 * Converts to HSV, divides V by @p factor, converts back; hue, saturation and alpha are
 * kept. A factor <= 0 or not finite returns @p c unchanged (QColor returns an invalid
 * colour there; unchanged is the safer choice for painting). A factor < 1 lightens, as in
 * Qt.
 *
 * WHY reimplemented: keeps this header Qt-free; the tests compare the result with
 * QColor::darker(int(factor * 100)) within one 8-bit step.
 *
 * @param c Colour.
 * @param factor Divisor of the HSV value.
 * @return Darkened colour.
 */
Rgba darker(const Rgba &c, double factor);

/**
 * @brief Fill colour of a button's disc.
 *
 * Rule (QML TrafficButton): pressed -> darker(typeColour, kPressedDarkerFactor);
 * else windowActive || groupHovered -> typeColour; else palette.idle.
 * typeColour is palette.close / minimize / maximize for the button kind.
 *
 * WHY the idle grey: an unfocused window shows neutral discs so attention goes to the
 * focused one; hovering brings the colours back so the buttons stay discoverable.
 *
 * @param kind Button kind.
 * @param state Visual state.
 * @param palette Palette of the current mode.
 * @return The disc colour, or std::nullopt for ButtonKind::Spacer (nothing is painted).
 */
std::optional<Rgba> discColor(ButtonKind kind, const ButtonVisualState &state, const ModePalette &palette);

/**
 * @brief Whole-button opacity (disc and glyph).
 * @param state Visual state.
 * @return 1.0 if state.enabled, else kDisabledOpacity.
 */
double buttonOpacity(const ButtonVisualState &state);

/**
 * @brief Whether glyphs are shown on this button.
 * @param state Visual state.
 * @return groupHovered || hovered || pressed.
 */
bool showGlyph(const ButtonVisualState &state);

/**
 * @brief Which glyph a button shows.
 *
 * Glyph::None if !showGlyph(state) or kind is Spacer; Close -> Glyph::Close;
 * Minimize -> Glyph::Minimize; Maximize -> Glyph::Restore if state.windowMaximized,
 * else Glyph::Maximize.
 *
 * @param kind Button kind.
 * @param state Visual state.
 * @return The glyph to draw.
 */
Glyph glyphFor(ButtonKind kind, const ButtonVisualState &state);

} // namespace Kuura::Deco
