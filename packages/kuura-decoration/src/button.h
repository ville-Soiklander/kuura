#pragma once

/**
 * @file button.h
 * @brief One round title-bar button (close, minimize, maximize/restore, or an empty
 *        spacer) drawn as a filled disc with a hover glyph.
 *
 * LOCKED INTERFACE (phase 1). Declarations only; the definitions go into button.cpp.
 *
 * KDECORATION3 API THIS CLASS RELIES ON (kdecoration v6.7.5 src/decorationbutton.h and
 * decorationbutton.cpp):
 *  - The protected constructor DecorationButton(type, Decoration *, QObject *parent)
 *    already wires the standard behaviour per type: Close -> requestClose and
 *    setEnabled(isCloseable) kept in sync; Minimize -> requestMinimize, enabled =
 *    isMinimizeable; Maximize -> requestToggleMaximization, checkable, checked =
 *    isMaximized kept in sync, enabled = isMaximizeable, accepts left/middle/right button;
 *    Spacer -> disabled. So this class adds NO click handling, only painting.
 *  - paint(QPainter *, const QRectF &repaintArea) is pure virtual; the painter is the
 *    decoration's painter (DecorationButtonGroup::paint() calls each visible button), so
 *    coordinates are decoration coordinates and geometry() is the disc rect.
 *  - hoveredChanged / pressedChanged / enabledChanged / checkedChanged signals; the
 *    decoration delivers hover and mouse events to buttons (Decoration::hoverMoveEvent(),
 *    mousePressEvent() in kdecoration src/decoration.cpp).
 *
 * DESIGN DECISIONS:
 *  - A disabled button stays VISIBLE and is dimmed (kDisabledOpacity), as in the QML
 *    theme. (Breeze instead hides it with setVisible(); we do not, so the group keeps
 *    the same width on every window and the discs never jump.)
 *  - Only Close, Minimize, Maximize and Spacer are created; create() returns nullptr for
 *    every other type, which DecorationButtonGroup skips (decorationbuttongroup.cpp:
 *    `if (DecorationButton *b = buttonCreator(...)) addButton(b)`).
 */

#include "geometry.h"
#include "palette_logic.h"

#include <KDecoration3/DecorationButton>

#include <QRectF>
#include <QVariantList>

class QPainter;

namespace KDecoration3
{
class Decoration;
}

namespace Kuura::Deco
{

class Decoration;

/**
 * @brief Map a framework button type to the kinds this decoration draws.
 * @param type KDecoration3 button type.
 * @param[out] kind Set to the matching ButtonKind when the function returns true.
 * @return true for Close, Minimize, Maximize and Spacer; false for every other type.
 */
bool buttonKindFor(KDecoration3::DecorationButtonType type, ButtonKind &kind);

/**
 * @brief A traffic-light button.
 *
 * Painting rule (palette_logic.h / geometry.h):
 *   state   = {window active, decoration buttonsHovered(), isHovered(), isPressed(),
 *              isEnabled(), isChecked()};
 *   opacity = buttonOpacity(state) for disc and glyph together;
 *   disc    = ellipse in geometry() filled with discColor(kind, state, palette);
 *   glyph   = glyphFor(kind, state): bars from glyphBars() (rounded caps, filled) and
 *             triangles from glyphTriangles(), in palette.glyphInk at kGlyphOpacity.
 * Antialiasing on. The Spacer paints nothing.
 *
 * Repaints: hoveredChanged, pressedChanged, enabledChanged and checkedChanged call
 * update(); a change of the decoration-wide hover flag or of the mode is repainted by the
 * Decoration. No animations (the QML theme had none).
 */
class Button : public KDecoration3::DecorationButton
{
    Q_OBJECT

public:
    /**
     * @brief Constructor used by the plugin factory for the settings page previews.
     *
     * Precondition (framework contract, kwin previewbridge.cpp createButton()):
     * args == {QVariant(DecorationButtonType), QVariant(KDecoration3::Decoration *)} and
     * the decoration was created by this plugin's factory. Sets the geometry to a disc at
     * the origin ({0, 0, diameter, diameter}) because the preview has no button group.
     * A violated precondition is a framework bug and is caught by Q_ASSERT in debug
     * builds; there is no recoverable error path because the base class needs a valid
     * decoration.
     *
     * @param parent QObject parent.
     * @param args {button type, decoration}.
     */
    explicit Button(QObject *parent, const QVariantList &args);

    /**
     * @brief Destroy.
     */
    ~Button() override;

    /**
     * @brief Button creator passed to DecorationButtonGroup.
     *
     * @param type Requested button type.
     * @param decoration The decoration; must be a Kuura::Deco::Decoration (checked with
     *        qobject_cast).
     * @param parent The group (QObject parent of the new button).
     * @return A new button sized {0, 0, diameter, diameter}, or nullptr if the type is not
     *         supported (buttonKindFor() false) or the decoration is not ours.
     */
    static Button *create(KDecoration3::DecorationButtonType type, KDecoration3::Decoration *decoration, QObject *parent);

    /**
     * @brief Paint the disc and, when shown, the glyph (see class comment).
     * @param painter The decoration's painter (decoration coordinates).
     * @param repaintArea Area being repainted; unused (a disc is tiny).
     */
    void paint(QPainter *painter, const QRectF &repaintArea) override;

    /**
     * @brief Which kind of traffic-light button this is.
     * @return The kind fixed at construction.
     */
    ButtonKind kind() const;

private:
    /**
     * @brief Common constructor.
     * @param type Supported button type (caller checked buttonKindFor()).
     * @param kind The matching kind.
     * @param decoration Owning decoration (non-null).
     * @param parent QObject parent.
     */
    Button(KDecoration3::DecorationButtonType type, ButtonKind kind, Decoration *decoration, QObject *parent);

    /**
     * @brief Collect the visual state from this button, its window and the decoration.
     * @return State for the palette_logic.h functions.
     */
    ButtonVisualState visualState() const;

    /**
     * @brief The owning decoration as our own type.
     * @return Non-null for every button this class creates.
     */
    Decoration *ownerDecoration() const;

    ButtonKind m_kind = ButtonKind::Spacer; ///< Fixed at construction.
};

} // namespace Kuura::Deco
