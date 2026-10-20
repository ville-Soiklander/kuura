// Implementation of decoration.h: the KDecoration3 glue around the Qt-free layout,
// palette and shadow logic. Every public function is documented in decoration.h;
// comments here explain the framework wiring and the non-obvious choices.

#include "decoration.h"

#include "button.h"

#include <KDecoration3/DecoratedWindow>
#include <KDecoration3/DecorationButtonGroup>

#include <QFontMetricsF>
#include <QHoverEvent>
#include <QImage>
#include <QMarginsF>
#include <QPainter>
#include <QTimer>

#include <array>

namespace Kuura::Deco
{

BorderPreset borderPresetFor(KDecoration3::BorderSize size)
{
    switch (size) {
    case KDecoration3::BorderSize::None:
        return BorderPreset::None;
    case KDecoration3::BorderSize::NoSides:
        return BorderPreset::NoSides;
    default:
        // Tiny .. Oversized all look the same in this design (geometry.h, BorderPreset).
        return BorderPreset::Normal;
    }
}

Rgba toRgba(const QColor &c)
{
    if (!c.isValid()) {
        return Rgba{0, 0, 0, 255};
    }
    return Rgba{static_cast<std::uint8_t>(c.red()), static_cast<std::uint8_t>(c.green()),
                static_cast<std::uint8_t>(c.blue()), static_cast<std::uint8_t>(c.alpha())};
}

QColor toQColor(const Rgba &c)
{
    return QColor::fromRgb(c.r, c.g, c.b, c.a);
}

QRectF toQRectF(const RectF &r)
{
    return QRectF(r.x, r.y, r.width, r.height);
}

namespace
{

/// Qt geometry -> geometry.h type (only needed here, so not part of the header).
RectF toRectF(const QRectF &r)
{
    return RectF{r.x(), r.y(), r.width(), r.height()};
}

/// geometry.h margins -> Qt, each edge snapped to the device pixel grid of @p scale.
QMarginsF toSnappedMargins(const MarginsF &m, double scale)
{
    return QMarginsF(snapToPixelGrid(m.left, scale), snapToPixelGrid(m.top, scale), snapToPixelGrid(m.right, scale),
                     snapToPixelGrid(m.bottom, scale));
}

} // namespace

Decoration::Decoration(QObject *parent, const QVariantList &args)
    : KDecoration3::Decoration(parent, args)
    // Plain data defaults only (no framework calls): they keep metrics()/modePalette()
    // meaningful even before init(), e.g. for a Button created by the settings preview.
    , m_metrics(tokenMetrics())
    , m_palette(tokenPalette(Mode::Light))
{
}

Decoration::~Decoration() = default;

bool Decoration::buttonsHovered() const
{
    return m_buttonsHovered;
}

Mode Decoration::mode() const
{
    return m_mode;
}

const ModePalette &Decoration::modePalette() const
{
    return m_palette;
}

const Metrics &Decoration::metrics() const
{
    return m_metrics;
}

QColor Decoration::titleBarColor() const
{
    const auto group = window()->isActive() ? KDecoration3::ColorGroup::Active : KDecoration3::ColorGroup::Inactive;
    return window()->color(group, KDecoration3::ColorRole::TitleBar);
}

QColor Decoration::captionColor() const
{
    const auto group = window()->isActive() ? KDecoration3::ColorGroup::Active : KDecoration3::ColorGroup::Inactive;
    return window()->color(group, KDecoration3::ColorRole::Foreground);
}

bool Decoration::init()
{
    // A missing window or settings object is a framework bug; without them nothing below
    // can run, so report failure and let KWin go without a decoration for this window.
    if (!window() || !settings()) {
        return false;
    }

    m_metrics = tokenMetrics();
    Q_ASSERT(isValid(m_metrics));

    updateMode();

    // The groups read the button lists from the settings, call our creator per type and
    // recreate the buttons themselves when the lists change (decorationbuttongroup.cpp).
    m_leftButtons = new KDecoration3::DecorationButtonGroup(KDecoration3::DecorationButtonGroup::Position::Left, this,
                                                            &Button::create);
    m_rightButtons = new KDecoration3::DecorationButtonGroup(KDecoration3::DecorationButtonGroup::Position::Right, this,
                                                             &Button::create);
    m_leftButtons->setSpacing(m_metrics.buttonSpacing);
    m_rightButtons->setSpacing(m_metrics.buttonSpacing);

    recalculateBorders();
    updateTitleBar();
    updateButtonsGeometry();
    updateShadow();
    setOpaque(window()->isMaximized());

    const auto s = settings();
    connect(s.get(), &KDecoration3::DecorationSettings::borderSizeChanged, this, &Decoration::recalculateBorders);
    connect(s.get(), &KDecoration3::DecorationSettings::reconfigured, this, &Decoration::recalculateBorders);
    connect(s.get(), &KDecoration3::DecorationSettings::fontChanged, this, [this]() {
        update();
    });
    // "Delayed": the group's own slot that recreates the buttons is connected to the same
    // signals and may run after ours, so sizing/positioning must wait for the event loop.
    connect(s.get(), &KDecoration3::DecorationSettings::decorationButtonsLeftChanged, this,
            &Decoration::updateButtonsGeometryDelayed);
    connect(s.get(), &KDecoration3::DecorationSettings::decorationButtonsRightChanged, this,
            &Decoration::updateButtonsGeometryDelayed);
    connect(s.get(), &KDecoration3::DecorationSettings::reconfigured, this, &Decoration::updateButtonsGeometryDelayed);

    KDecoration3::DecoratedWindow *w = window();
    connect(w, &KDecoration3::DecoratedWindow::activeChanged, this, [this]() {
        update();
    });
    connect(w, &KDecoration3::DecoratedWindow::captionChanged, this, [this]() {
        update(titleBar());
    });
    connect(w, &KDecoration3::DecoratedWindow::widthChanged, this, &Decoration::updateTitleBar);
    connect(w, &KDecoration3::DecoratedWindow::widthChanged, this, &Decoration::updateButtonsGeometry);

    // Every maximize transition changes borders, radius, outline, title bar, button
    // positions, shadow and opacity together; one handler keeps them consistent.
    const auto onMaximizeChange = [this]() {
        recalculateBorders();
        updateTitleBar();
        updateButtonsGeometry();
        updateShadow();
        setOpaque(window()->isMaximized());
    };
    connect(w, &KDecoration3::DecoratedWindow::maximizedChanged, this, onMaximizeChange);
    connect(w, &KDecoration3::DecoratedWindow::maximizedHorizontallyChanged, this, onMaximizeChange);
    connect(w, &KDecoration3::DecoratedWindow::maximizedVerticallyChanged, this, onMaximizeChange);
    connect(w, &KDecoration3::DecoratedWindow::paletteChanged, this, &Decoration::updateMode);
    connect(w, &KDecoration3::DecoratedWindow::nextScaleChanged, this, &Decoration::recalculateBorders);

    // borders() is the CURRENT state, which changes only when KWin applies the next state;
    // the title bar is derived from it, so it follows that signal.
    connect(this, &KDecoration3::Decoration::bordersChanged, this, &Decoration::updateTitleBar);

    return true;
}

void Decoration::paint(QPainter *painter, const QRectF &repaintArea)
{
    Q_UNUSED(repaintArea)
    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);

    // Background: one fill for title bar and borders. With compositing KWin clips the
    // window to the same radius, the rounded fill only gives the edge its antialiasing;
    // without an alpha channel nothing would blend the corners, so a plain rect is used.
    const QRectF frame = rect();
    painter->setPen(Qt::NoPen);
    painter->setBrush(titleBarColor());
    const double radius = cornerRadius(m_metrics, window()->isMaximized());
    if (settings()->isAlphaChannelSupported() && radius > 0.0) {
        painter->drawRoundedRect(frame, radius, radius);
    } else {
        painter->drawRect(frame);
    }

    // Caption, centred in the whole bar (symmetric padding, geometry.h captionRect()).
    const double leftWidth = m_leftButtons ? m_leftButtons->geometry().width() : 0.0;
    const double rightWidth = m_rightButtons ? m_rightButtons->geometry().width() : 0.0;
    const QRectF captionArea = toQRectF(captionRect(frame.width(), leftWidth, rightWidth, m_metrics));
    if (captionArea.width() > 0.0) {
        const QFont font = settings()->font();
        const QFontMetricsF fm(font);
        const QString text = fm.elidedText(window()->caption(), Qt::ElideMiddle, captionArea.width());
        painter->setFont(font);
        painter->setPen(captionColor());
        painter->drawText(captionArea, Qt::AlignCenter | Qt::TextSingleLine, text);
    }

    if (m_leftButtons) {
        m_leftButtons->paint(painter, repaintArea);
    }
    if (m_rightButtons) {
        m_rightButtons->paint(painter, repaintArea);
    }
    painter->restore();
}

void Decoration::hoverMoveEvent(QHoverEvent *event)
{
    KDecoration3::Decoration::hoverMoveEvent(event);

    // KDecoration3 only knows per-button hover and skips disabled buttons, but the glyphs
    // must appear on ALL discs while the pointer is anywhere over the group, gaps included.
    const QPointF pos = event->position();
    const PointF p{pos.x(), pos.y()};
    bool inside = false;
    for (const KDecoration3::DecorationButtonGroup *group : {m_leftButtons, m_rightButtons}) {
        if (group && contains(hoverZone(toRectF(group->geometry()), m_metrics), p)) {
            inside = true;
        }
    }
    setButtonsHovered(inside);
}

void Decoration::hoverLeaveEvent(QHoverEvent *event)
{
    KDecoration3::Decoration::hoverLeaveEvent(event);
    setButtonsHovered(false);
}

void Decoration::recalculateBorders()
{
    KDecoration3::DecoratedWindow *w = window();
    const double scale = w->nextScale();
    const bool maximized = w->isMaximized();
    const BorderPreset preset = borderPresetFor(settings()->borderSize());

    // Snapped at the NEXT scale because these values go into the next state, which KWin
    // applies together with a scale change (as Breeze does on nextScaleChanged).
    setBorders(toSnappedMargins(frameBorders(m_metrics, preset, maximized), scale));
    // Qualified: the inherited KDecoration3::Decoration::resizeOnlyBorders() getter hides
    // the free geometry.h function of the same name inside this member function.
    setResizeOnlyBorders(toSnappedMargins(
        Kuura::Deco::resizeOnlyBorders(preset, w->isMaximizedHorizontally(), w->isMaximizedVertically()), scale));

    const double radius = snapToPixelGrid(cornerRadius(m_metrics, maximized), scale);
    // All four corners: KWin clips decoration AND client with this radius, which is what
    // rounds the bottom corners (the reason this plugin exists).
    const KDecoration3::BorderRadius borderRadius(radius);
    setBorderRadius(borderRadius);
    if (maximized) {
        setBorderOutline(KDecoration3::BorderOutline());
    } else {
        setBorderOutline(KDecoration3::BorderOutline(outlineThickness(m_metrics, scale), toQColor(m_palette.separator),
                                                     borderRadius));
    }
}

void Decoration::updateTitleBar()
{
    const QMarginsF b = borders();
    const MarginsF current{b.left(), b.top(), b.right(), b.bottom()};
    setTitleBar(toQRectF(titleBarRect(m_metrics, rect().width(), current, window()->isMaximized())));
}

void Decoration::updateButtonsGeometry()
{
    if (!m_leftButtons || !m_rightButtons) {
        return;
    }
    // Each button is exactly the disc; the group assigns positions inside itself.
    const QRectF disc(0.0, 0.0, m_metrics.buttonDiameter, m_metrics.buttonDiameter);
    const auto buttons = m_leftButtons->buttons() + m_rightButtons->buttons();
    for (KDecoration3::DecorationButton *button : buttons) {
        button->setGeometry(disc);
    }

    // The live group width is used (not buttonGroupWidth()) so a group the framework laid
    // out differently, e.g. with a hidden button, is still placed flush with the inset.
    const double width = rect().width();
    const PointF left = buttonGroupOrigin(GroupSide::Left, width, m_leftButtons->geometry().width(), m_metrics);
    const PointF right = buttonGroupOrigin(GroupSide::Right, width, m_rightButtons->geometry().width(), m_metrics);
    m_leftButtons->setPos(QPointF(left.x, left.y));
    m_rightButtons->setPos(QPointF(right.x, right.y));
    update();
}

void Decoration::updateButtonsGeometryDelayed()
{
    QTimer::singleShot(0, this, &Decoration::updateButtonsGeometry);
}

void Decoration::updateMode()
{
    // The ACTIVE title-bar colour decides, even for an inactive window, so the mode cannot
    // flip on a focus change (palette_logic.h, modeForBackground()).
    const Mode next = modeForBackground(
        toRgba(window()->color(KDecoration3::ColorGroup::Active, KDecoration3::ColorRole::TitleBar)));
    if (next == m_mode) {
        return;
    }
    m_mode = next;
    m_palette = tokenPalette(m_mode);
    recalculateBorders(); // outline colour
    updateShadow();
    update();
}

void Decoration::updateShadow()
{
    if (window()->isMaximized()) {
        setShadow(nullptr);
        return;
    }
    setShadow(sharedShadow(m_mode));
}

void Decoration::setButtonsHovered(bool hovered)
{
    if (hovered == m_buttonsHovered) {
        return;
    }
    m_buttonsHovered = hovered;
    // Every disc changes (glyphs, and colours on an unfocused window), so repaint both
    // groups; the buttons themselves only repaint on their own state changes.
    for (const KDecoration3::DecorationButtonGroup *group : {m_leftButtons, m_rightButtons}) {
        if (group) {
            update(group->geometry());
        }
    }
}

std::shared_ptr<KDecoration3::DecorationShadow> Decoration::sharedShadow(Mode mode)
{
    // One cache slot per mode. `built` is separate from the pointer because nullptr is a
    // valid, cached result (shadow disabled by the tokens).
    struct Slot {
        bool built = false;
        std::shared_ptr<KDecoration3::DecorationShadow> shadow;
    };
    static std::array<Slot, 2> cache;
    Slot &slot = cache[mode == Mode::Dark ? 1 : 0];
    if (slot.built) {
        return slot.shadow;
    }
    slot.built = true;

    const ShadowImage mask = renderShadowImage(shadowParams(tokenMetrics(), tokenPalette(mode)));
    if (mask.width <= 0 || mask.height <= 0) {
        return slot.shadow; // nullptr
    }

    // The logic renders straight opacity; KWin wants a premultiplied ARGB image, so the
    // shadow colour is applied and premultiplied per pixel here.
    QImage image(mask.width, mask.height, QImage::Format_ARGB32_Premultiplied);
    for (int y = 0; y < mask.height; ++y) {
        auto *line = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < mask.width; ++x) {
            const int a = mask.alpha[static_cast<std::size_t>(y) * static_cast<std::size_t>(mask.width)
                                     + static_cast<std::size_t>(x)];
            line[x] = qPremultiply(qRgba(mask.colour.r, mask.colour.g, mask.colour.b, a));
        }
    }

    auto shadow = std::make_shared<KDecoration3::DecorationShadow>();
    shadow->setPadding(QMarginsF(mask.padding.left, mask.padding.top, mask.padding.right, mask.padding.bottom));
    shadow->setInnerShadowRect(toQRectF(mask.innerShadowRect));
    shadow->setShadow(image);
    slot.shadow = shadow;
    return slot.shadow;
}

} // namespace Kuura::Deco
