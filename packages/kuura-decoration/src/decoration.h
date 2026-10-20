#pragma once

/**
 * @file decoration.h
 * @brief The KDecoration3 window decoration with round traffic-light buttons on the left,
 *        a title bar coloured from the active colour scheme, a drop shadow, a hairline
 *        outline and rounded corners on ALL FOUR sides.
 *
 * LOCKED INTERFACE (phase 1). Declarations only; the definitions go into decoration.cpp
 * (class) and plugin.cpp (the plugin factory, see "Plugin entry point" below).
 *
 * WHY a C++ plugin instead of the Aurorae QML theme: rounding the bottom corners needs
 * KDecoration3::Decoration::setBorderRadius(), which is PROTECTED (kdecoration v6.7.5
 * src/decoration.h) and not exposed to QML by aurorae; only a Decoration subclass can call
 * it (docs/SHELL_CONTRACT.md, "Rounded bottom corners: impossible from QML").
 *
 * KDECORATION3 API THIS CLASS RELIES ON (all kdecoration tag v6.7.5, src/decoration.h
 * unless noted; Breeze v6.7.5 kdecoration/breezedecoration.{h,cpp} read as reference
 * only, no code copied):
 *  - Constructor signature (QObject *parent, const QVariantList &args): KWin creates the
 *    decoration with KPluginFactory::create<KDecoration3::Decoration>(window,
 *    QVariantList{args}) where args holds "bridge" (and "theme" only for theme-based
 *    plugins) (kwin src/decorations/decorationbridge.cpp, createDecoration()). The base
 *    constructor needs those args to find the bridge, so they must be passed through.
 *  - Life cycle: KWin calls setSettings(), create(), then init() (same function). All
 *    set-up therefore happens in init(), never in the constructor (doc of init()).
 *  - paint(QPainter *, const QRectF &repaintArea) is pure virtual; the painter targets an
 *    implicitly double-buffered device in decoration coordinates (doc of paint()).
 *  - setBorders / setResizeOnlyBorders / setTitleBar / setOpaque / setShadow /
 *    setBorderRadius / setBorderOutline are protected setters. In KDecoration3 borders,
 *    border radius and outline are double-buffered DecorationState: the setters write
 *    the "next" state and KWin applies it when it reconfigures the window
 *    (decoration.cpp: setBorders() -> setState(); setState() emits nextStateChanged).
 *  - KWin clips the whole window (decoration + client) to the frame with the border radius
 *    (kwin src/scene/windowitem.cpp, updateBorderRadius()); BorderOutline is drawn by KWin
 *    OUTSIDE the frame, inflated by its thickness, following the same radius
 *    (kwin src/scene/outlinedborderitem.cpp, OutlinedBorderItem: geometry =
 *    outline.inflate(innerRect)).
 *  - DecoratedWindow (src/decoratedwindow.h): isActive, isMaximized,
 *    isMaximizedHorizontally/Vertically, width, caption, color(ColorGroup, ColorRole),
 *    nextScale() and the matching *Changed signals, paletteChanged, nextScaleChanged.
 *  - DecorationSettings (src/decorationsettings.h): borderSize(), font(),
 *    isAlphaChannelSupported(), signals borderSizeChanged, fontChanged,
 *    decorationButtonsLeftChanged/RightChanged, reconfigured.
 *  - DecorationButtonGroup (src/decorationbuttongroup.h): the (Position, Decoration*,
 *    creator) constructor reads the left/right button lists from the settings, calls the
 *    creator per type, and RECREATES the buttons itself on decorationButtons*Changed
 *    (decorationbuttongroup.cpp). Layout: setSpacing(), setPos(); it positions visible
 *    buttons and mirrors them for right-to-left sessions; paint() paints its buttons.
 *
 * C++ STANDARD: C++20 is required, because <KDecoration3/Decoration> itself uses a
 * defaulted operator<=> (BorderRadius).
 */

#include "geometry.h"
#include "palette_logic.h"
#include "shadow_logic.h"

#include <KDecoration3/Decoration>
#include <KDecoration3/DecorationSettings>
#include <KDecoration3/DecorationShadow>

#include <QColor>
#include <QRectF>
#include <QVariantList>

#include <memory>

class QHoverEvent;
class QPainter;

namespace KDecoration3
{
class DecorationButtonGroup;
}

namespace Kuura::Deco
{

/**
 * @brief Map the framework's border size to the three presets the design distinguishes.
 *
 * None -> BorderPreset::None, NoSides -> BorderPreset::NoSides, everything else ->
 * BorderPreset::Normal (see geometry.h, BorderPreset).
 *
 * @param size Value of DecorationSettings::borderSize().
 * @return The preset.
 */
BorderPreset borderPresetFor(KDecoration3::BorderSize size);

/**
 * @brief Convert a QColor to the Qt-free Rgba used by palette_logic.h.
 * @param c Colour; an invalid QColor converts to opaque black (DecoratedWindow::color()
 *        returns an invalid colour for an unknown group/role combination).
 * @return 8-bit RGBA.
 */
Rgba toRgba(const QColor &c);

/**
 * @brief Convert an Rgba to QColor.
 * @param c Colour.
 * @return The same colour as QColor (QColor::fromRgb with alpha).
 */
QColor toQColor(const Rgba &c);

/**
 * @brief Convert geometry.h types to Qt.
 * @param r Rectangle in decoration coordinates.
 * @return QRectF(r.x, r.y, r.width, r.height).
 */
QRectF toQRectF(const RectF &r);

/**
 * @brief The window decoration.
 *
 * Behaviour (the spec of docs/SHELL_CONTRACT.md, "Window decoration"):
 *  - Title bar of Metrics::titleBarHeight filled with the scheme's title-bar colour
 *    (active or inactive group), the caption in the scheme's foreground colour and
 *    DecorationSettings::font(), centred in the whole bar, elided in the middle.
 *  - Close, minimize, maximize discs in the order of DecorationSettings
 *    (kwinrc ButtonsOnLeft=XIA), drawn by Button (button.h).
 *  - Glyphs on ALL discs while the pointer is in either group's hoverZone(); tracked here
 *    (buttonsHovered()) because KDecoration3 only knows per-button hover.
 *  - Borders by frameBorders()/resizeOnlyBorders(); the side and bottom borders are
 *    painted in the title-bar colour.
 *  - Border radius on all four corners (cornerRadius()), outline of outlineThickness() in
 *    the mode's separator colour, both removed while maximized.
 *  - Drop shadow from renderShadowImage(), removed while maximized or when
 *    shadow_size == 0; shared between all windows of the same mode.
 *  - Light/dark: mode() follows modeForBackground() of the ACTIVE title-bar colour and is
 *    re-evaluated on DecoratedWindow::paletteChanged; the outline colour and the shadow
 *    are updated then too (the title bar repaints by itself, KWin triggers that).
 *  - Scale: all lengths are snapped at DecoratedWindow::nextScale() and recomputed on
 *    nextScaleChanged (as Breeze's updateScale()).
 *
 * Errors: init() returns false only if the window or settings are missing (a framework
 * bug); KWin then has no decoration for that window. Nothing here throws.
 */
class Decoration : public KDecoration3::Decoration
{
    Q_OBJECT

public:
    /**
     * @brief Construct; does no set-up (see init()).
     *
     * Registered with the plugin factory, so this exact signature is required.
     *
     * @param parent Owner passed by KWin (the KWin window object).
     * @param args Framework arguments ("bridge", optionally "theme"); passed unchanged to
     *        KDecoration3::Decoration.
     */
    explicit Decoration(QObject *parent = nullptr, const QVariantList &args = QVariantList());

    /**
     * @brief Destroy; the button groups are QObject children and go with it.
     */
    ~Decoration() override;

    /**
     * @brief Paint the frame, title bar, caption and both button groups.
     *
     * Order: fill the whole decoration rect() with the title-bar colour (a rounded rect of
     * cornerRadius() when DecorationSettings::isAlphaChannelSupported(), a plain rect
     * otherwise - without compositing nothing clips or blends the corners), then the
     * caption into captionRect(), then m_leftButtons->paint() and m_rightButtons->paint().
     * Antialiasing on. The outline and the shadow are NOT painted here (KWin draws them).
     *
     * @param painter Painter on the decoration's buffer, in decoration coordinates.
     * @param repaintArea Area that needs repainting; painting outside it is allowed.
     */
    void paint(QPainter *painter, const QRectF &repaintArea) override;

    /**
     * @brief True while the pointer is in a hoverZone(); every Button then shows its glyph.
     * @return The decoration-wide hover flag.
     */
    bool buttonsHovered() const;

    /**
     * @brief Current light/dark mode (see modeForBackground()).
     * @return The mode last computed by updateMode().
     */
    Mode mode() const;

    /**
     * @brief Token palette of the current mode; read by Button::paint().
     * @return Reference valid for the decoration's lifetime.
     */
    const ModePalette &modePalette() const;

    /**
     * @brief Layout metrics (tokenMetrics(), validated in init()).
     * @return Reference valid for the decoration's lifetime.
     */
    const Metrics &metrics() const;

    /**
     * @brief Title-bar background for the window's current focus state.
     * @return DecoratedWindow::color(Active or Inactive, ColorRole::TitleBar).
     */
    QColor titleBarColor() const;

    /**
     * @brief Caption colour for the window's current focus state.
     * @return DecoratedWindow::color(Active or Inactive, ColorRole::Foreground).
     */
    QColor captionColor() const;

public Q_SLOTS:
    /**
     * @brief Set up the decoration; called once by KWin after create().
     *
     * Steps: metrics = tokenMetrics() (asserted isValid()); updateMode(); create both
     * DecorationButtonGroup objects with Button::create as creator and spacing
     * Metrics::buttonSpacing; recalculateBorders(); updateTitleBar();
     * updateButtonsGeometry(); updateShadow(); connect the signals:
     *  - settings: borderSizeChanged, reconfigured -> recalculateBorders;
     *    fontChanged -> update(); decorationButtonsLeftChanged/RightChanged and
     *    reconfigured -> updateButtonsGeometryDelayed (the group recreates its buttons in
     *    its own slot, which may run after ours, hence "delayed"; Breeze does the same).
     *  - window: activeChanged -> update(); captionChanged -> update(titleBar());
     *    widthChanged -> updateTitleBar + updateButtonsGeometry;
     *    maximizedChanged, maximizedHorizontallyChanged, maximizedVerticallyChanged ->
     *    recalculateBorders + updateTitleBar + updateButtonsGeometry + updateShadow, and
     *    setOpaque(isMaximized()); paletteChanged -> updateMode;
     *    nextScaleChanged -> recalculateBorders.
     *  - this: bordersChanged -> updateTitleBar.
     *
     * @return true on success; false if window() or settings() is null.
     */
    bool init() override;

protected:
    /**
     * @brief Forward to the base (per-button hover, section under mouse), then update the
     *        group hover flag from the pointer position.
     * @param event Hover event in decoration coordinates.
     */
    void hoverMoveEvent(QHoverEvent *event) override;

    /**
     * @brief Forward to the base, then clear the group hover flag.
     * @param event Hover event.
     */
    void hoverLeaveEvent(QHoverEvent *event) override;

private Q_SLOTS:
    /**
     * @brief Recompute borders, resize-only borders, border radius and outline.
     *
     * setBorders(snapped frameBorders()), setResizeOnlyBorders(resizeOnlyBorders()),
     * setBorderRadius(BorderRadius(cornerRadius())) - all four corners -, and
     * setBorderOutline(BorderOutline(outlineThickness(), separator, radius)) or an empty
     * BorderOutline() while maximized. Snapped at window()->nextScale().
     */
    void recalculateBorders();

    /**
     * @brief setTitleBar(titleBarRect()) for the current width, borders and maximize state.
     */
    void updateTitleBar();

    /**
     * @brief Size every button to the disc, position both groups (buttonGroupOrigin()),
     *        then update().
     */
    void updateButtonsGeometry();

    /**
     * @brief Run updateButtonsGeometry() from the event loop (QTimer::singleShot(0)).
     */
    void updateButtonsGeometryDelayed();

    /**
     * @brief Re-evaluate mode(); on a change update the outline colour
     *        (recalculateBorders()), the shadow (updateShadow()) and repaint.
     */
    void updateMode();

    /**
     * @brief setShadow(sharedShadow(mode())) for a floating window, setShadow(nullptr)
     *        while maximized or when the shadow is empty.
     */
    void updateShadow();

private:
    /**
     * @brief Set the group hover flag; on a change repaint both groups.
     * @param hovered New value.
     */
    void setButtonsHovered(bool hovered);

    /**
     * @brief Shadow object shared by all decorations of a mode, built lazily from
     *        renderShadowImage(shadowParams(metrics, tokenPalette(mode))).
     *
     * WHY shared: the image depends only on tokens and mode, and KWin can reuse one
     * texture for many windows (decorationshadow.h class comment; Breeze keeps static
     * shadow objects for the same reason).
     *
     * @param mode Light or Dark.
     * @return The shadow, or nullptr if the shadow is disabled (shadow_size 0).
     */
    static std::shared_ptr<KDecoration3::DecorationShadow> sharedShadow(Mode mode);

    KDecoration3::DecorationButtonGroup *m_leftButtons = nullptr;  ///< Owned via QObject parent.
    KDecoration3::DecorationButtonGroup *m_rightButtons = nullptr; ///< Owned via QObject parent.
    Metrics m_metrics;                                             ///< tokenMetrics().
    Mode m_mode = Mode::Light;                                     ///< See updateMode().
    ModePalette m_palette;                                         ///< tokenPalette(m_mode).
    bool m_buttonsHovered = false;                                 ///< See buttonsHovered().
};

/*
 * Plugin entry point (plugin.cpp, not a header):
 *
 *   K_PLUGIN_FACTORY_WITH_JSON(KuuraDecorationFactory, "metadata.json",
 *                              registerPlugin<Kuura::Deco::Decoration>();
 *                              registerPlugin<Kuura::Deco::Button>();)
 *   #include "plugin.moc"
 *
 * WHY both registrations: KWin asks the factory for a KDecoration3::Decoration
 * (decorationbridge.cpp, createDecoration()), and the Window Decorations settings page
 * asks it for a KDecoration3::DecorationButton with args {type, decoration} to draw its
 * button previews (kwin src/kcms/decoration/declarative-plugin/previewbridge.cpp,
 * createButton()). Breeze registers the same pair (breezedecoration.cpp). The json is the
 * configure-time generated metadata.json (INTERFACE_NOTES.md), embedded by moc, so its
 * directory must be on the include path.
 */

} // namespace Kuura::Deco
