// Implementation of button.h: one traffic-light disc with its hover glyph. Behaviour
// (click actions, enabled/checked state) comes from KDecoration3::DecorationButton;
// this file only paints.

#include "button.h"

#include "decoration.h"

#include <KDecoration3/DecoratedWindow>

#include <QPainter>
#include <QPolygonF>

#include <algorithm>

namespace Kuura::Deco
{

bool buttonKindFor(KDecoration3::DecorationButtonType type, ButtonKind &kind)
{
    switch (type) {
    case KDecoration3::DecorationButtonType::Close:
        kind = ButtonKind::Close;
        return true;
    case KDecoration3::DecorationButtonType::Minimize:
        kind = ButtonKind::Minimize;
        return true;
    case KDecoration3::DecorationButtonType::Maximize:
        kind = ButtonKind::Maximize;
        return true;
    case KDecoration3::DecorationButtonType::Spacer:
        kind = ButtonKind::Spacer;
        return true;
    default:
        return false;
    }
}

namespace
{

/// Button type from the settings-preview arguments (see the Button(QObject*, args) doc).
KDecoration3::DecorationButtonType argType(const QVariantList &args)
{
    Q_ASSERT(args.size() >= 2);
    return args.value(0).value<KDecoration3::DecorationButtonType>();
}

/// Our decoration from the settings-preview arguments; nullptr if it is not ours.
Decoration *argDecoration(const QVariantList &args)
{
    Q_ASSERT(args.size() >= 2);
    auto *deco = qobject_cast<Decoration *>(args.value(1).value<KDecoration3::Decoration *>());
    Q_ASSERT(deco);
    return deco;
}

/// Kind for the preview path; an unsupported type is drawn as an (invisible) Spacer
/// rather than crashing, since the base class is already committed to that type.
ButtonKind argKind(const QVariantList &args)
{
    ButtonKind kind = ButtonKind::Spacer;
    buttonKindFor(argType(args), kind);
    return kind;
}

} // namespace

Button::Button(QObject *parent, const QVariantList &args)
    : Button(argType(args), argKind(args), argDecoration(args), parent)
{
    // The preview has no button group to size the button; it resizes it itself later.
    const double d = ownerDecoration() ? ownerDecoration()->metrics().buttonDiameter : 0.0;
    setGeometry(QRectF(0.0, 0.0, d, d));
}

Button::Button(KDecoration3::DecorationButtonType type, ButtonKind kind, Decoration *decoration, QObject *parent)
    : KDecoration3::DecorationButton(type, decoration, parent)
    , m_kind(kind)
{
    // Repaint on every own state change that alters the look; click handling and the
    // enabled/checked bookkeeping are already wired by the base constructor.
    const auto repaint = [this]() {
        update();
    };
    connect(this, &KDecoration3::DecorationButton::hoveredChanged, this, repaint);
    connect(this, &KDecoration3::DecorationButton::pressedChanged, this, repaint);
    connect(this, &KDecoration3::DecorationButton::enabledChanged, this, repaint);
    connect(this, &KDecoration3::DecorationButton::checkedChanged, this, repaint);
}

Button::~Button() = default;

Button *Button::create(KDecoration3::DecorationButtonType type, KDecoration3::Decoration *decoration, QObject *parent)
{
    ButtonKind kind = ButtonKind::Spacer;
    if (!buttonKindFor(type, kind)) {
        return nullptr; // the group skips nullptr (decorationbuttongroup.cpp)
    }
    auto *deco = qobject_cast<Decoration *>(decoration);
    if (!deco) {
        return nullptr;
    }
    // Qt object-tree ownership: the decoration button group that called this creator
    // takes over the pointer.
    // NOLINTNEXTLINE(cppcoreguidelines-owning-memory)
    auto *button = new Button(type, kind, deco, parent);
    const double d = deco->metrics().buttonDiameter;
    button->setGeometry(QRectF(0.0, 0.0, d, d));
    return button;
}

ButtonKind Button::kind() const
{
    return m_kind;
}

Decoration *Button::ownerDecoration() const
{
    return qobject_cast<Decoration *>(decoration());
}

ButtonVisualState Button::visualState() const
{
    ButtonVisualState s;
    const Decoration *deco = ownerDecoration();
    s.windowActive = deco && deco->window() && deco->window()->isActive();
    s.groupHovered = deco && deco->buttonsHovered();
    s.hovered = isHovered();
    s.pressed = isPressed();
    s.enabled = isEnabled();
    s.windowMaximized = isChecked();
    return s;
}

void Button::paint(QPainter *painter, const QRectF &repaintArea)
{
    Q_UNUSED(repaintArea)
    const Decoration *deco = ownerDecoration();
    if (!deco) {
        return;
    }
    const ButtonVisualState state = visualState();
    const ModePalette &palette = deco->modePalette();
    const std::optional<Rgba> fill = discColor(m_kind, state, palette);
    if (!fill) {
        return; // Spacer
    }

    // The disc is the largest centred square in geometry(): in a group geometry() is
    // already square, the settings preview may hand us a non-square item.
    const QRectF g = geometry();
    const double side = std::min(g.width(), g.height());
    const RectF disc{.x = g.x() + (g.width() - side) / 2.0,
                     .y = g.y() + (g.height() - side) / 2.0,
                     .width = side,
                     .height = side};

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);
    // Disc and glyph fade together for a disabled button.
    painter->setOpacity(painter->opacity() * buttonOpacity(state));
    painter->setPen(Qt::NoPen);
    painter->setBrush(toQColor(*fill));
    painter->drawEllipse(toQRectF(disc));

    const Glyph glyph = glyphFor(m_kind, state);
    if (glyph != Glyph::None) {
        QColor ink = toQColor(palette.glyphInk);
        ink.setAlphaF(static_cast<float>(ink.alphaF() * kGlyphOpacity));
        painter->setBrush(ink);

        // Bars are drawn as rounded rects in a rotated coordinate system centred on the
        // bar, so the caps stay round at any angle.
        for (const GlyphBar &bar : glyphBars(glyph, disc, deco->metrics().glyphStroke)) {
            painter->save();
            painter->translate(bar.centre.x, bar.centre.y);
            painter->rotate(bar.angleDegrees);
            const double r = bar.thickness / 2.0;
            painter->drawRoundedRect(QRectF(-bar.length / 2.0, -r, bar.length, bar.thickness), r, r);
            painter->restore();
        }
        for (const GridTriangle &t : glyphTriangles(glyph, disc)) {
            // Range-for instead of t[0..2]: no unchecked indexing, same three vertices.
            QPolygonF poly;
            for (const PointF &vertex : t) {
                poly << QPointF(vertex.x, vertex.y);
            }
            painter->drawPolygon(poly);
        }
    }
    painter->restore();
}

} // namespace Kuura::Deco
