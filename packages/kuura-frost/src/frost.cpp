#include "frost.h"
#include "frost_shader.h"

// Confirmed live at /usr/include/kwin/opengl/glshadermanager.h,
// /usr/include/kwin/opengl/glshader.h and /usr/include/kwin/opengl/gltexture.h
// against the pinned Arch snapshot's kwin package (V4 investigation notes).
// gltexture.h itself #includes <epoxy/gl.h> (confirmed by reading it directly),
// which is where apply()'s own glActiveTexture()/GL_TEXTURE0/GL_TEXTURE1 calls
// come from -- no separate raw-GL include is needed.
#include <opengl/glshader.h>
#include <opengl/glshadermanager.h>
#include <opengl/gltexture.h>
#include <effect/effecthandler.h>
#include <effect/effectwindow.h>
// snapToPixels(): the SAME rounding OffscreenData::maybeRender() applies to the
// window's expanded geometry before sizing Frost's captured texture
// (effect/offscreeneffect.cpp at the pinned tag) -- apply() must reproduce it
// exactly so the glass rect lands on the same device-pixel grid as the texture.
#include <core/pixelgrid.h>
// Backdrop refraction (drawWindow()/refractBackdrop()): the same headers
// plugins/blur/blur.cpp includes for its own backdrop read and on-screen draw.
#include <core/rendertarget.h>
#include <core/renderviewport.h>
#include <opengl/glframebuffer.h>
#include <opengl/glvertexbuffer.h>

// The generated tokens.h below is a package-build-time artifact (see
// design/generators/cpp_header.py and packages/kuura-frost/PKGBUILD's build()),
// not a checked-in source file -- packages/kuura-frost/CMakeLists.txt adds its
// real, generated location (<package dir>/generated/cpp/) to this target's
// include path. This is the ONE place design/tokens.json's material.* numbers
// reach this file; nothing below hand-copies a tokens.json value as a literal
// (frost.h's own class docstring explicitly forbids that).
#include <tokens.h>

#include <QImage>
#include <QMatrix4x4>
#include <QRandomGenerator>
#include <QVector2D>
#include <QVector4D>

// Confirmed live at /usr/include/kwin/wayland/surface.h -- KWin's OWN,
// internally-namespaced Wayland server implementation (KWin::SurfaceInterface),
// not the separate/external KWaylandServer library an older KWin version used.
// This is the SAME header, type and blurRegion()/blurChanged accessor
// BlurEffect itself uses (src/plugins/blur/blur.cpp at the pinned tag,
// v6.7.5, commit ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7) -- confirmed by
// fetching and reading that file directly, not guessed.
#include <wayland/surface.h>
#include <window.h>

#if KWIN_BUILD_X11
// Confirmed live: `find /usr/include/kwin -iname '*xcbutils*' -o -iname
// '*x11window*'` in the pinned build container lists both headers -- KWin
// installs its FULL internal header tree for out-of-tree plugins (there is no
// separate, curated "public effect API" subset, consistent with frost.h's own
// class docstring noting the effect ABI is not stable across versions anyway).
// This is why blur.cpp's own X11 accessor chain below can be reused almost
// verbatim.
#include <utils/xcbutils.h>
#include <x11window.h>
#endif

#include <KDecoration3/Decoration>

#include <QDynamicPropertyChangeEvent>
#include <QWindow>

#include <cmath>
#include <span>

namespace Kuura
{

#if KWIN_BUILD_X11
// The SAME X11 property BlurEffect announces and reads. Frost asks the
// identical question ("does this window want the glass material") through
// the identical legacy mechanism -- not a Frost-specific atom. Confirmed
// verbatim from blur.cpp's own s_blurAtomName at the pinned tag. Sharing one
// atom name between two effects is the normal, safe KWin pattern: see
// requestedEffectChainPosition()'s own docstring in frost.h for the
// announceSupportProperty()/removeSupportProperty() citation.
// Identical static storage duration pattern to blur.cpp's own s_blurAtomName
// at the pinned tag (QByteArrayLiteral wraps a compile-time literal; it does
// not allocate or throw in practice, and KWin's own upstream code uses
// exactly this idiom).
// NOLINTNEXTLINE(bugprone-throwing-static-initialization)
static const QByteArray s_blurAtomName = QByteArrayLiteral("_KDE_NET_WM_BLUR_BEHIND_REGION");
#endif

Frost::Frost()
{
    // WHY connect here, not rely on a base-class default: OffscreenEffect
    // does not itself decide which windows to redirect -- that is this
    // effect's own responsibility, following BlurEffect::slotWindowAdded()'s
    // precedent exactly (see frost.h's class docstring). `effects` is
    // KWin's real global EffectsHandler pointer, used the same way
    // throughout its own effect plugins, including blur.cpp.
    connect(KWin::effects, &KWin::EffectsHandler::windowAdded, this, &Frost::slotWindowAdded);
    connect(KWin::effects, &KWin::EffectsHandler::windowDeleted, this, &Frost::slotWindowDeleted);
    // Backdrop copies are per view (output); free them when one goes away,
    // as BlurEffect's constructor does with the same signal (blur.cpp).
    connect(KWin::effects, &KWin::EffectsHandler::viewRemoved, this, &Frost::slotViewRemoved);

#if KWIN_BUILD_X11
    // Mirrors BlurEffect's own constructor exactly (blur.cpp: announce once,
    // then re-announce whenever the X11 connection itself changes, e.g. an
    // XWayland restart).
    if (KWin::effects->xcbConnection()) {
        m_netWmBlurRegion = KWin::effects->announceSupportProperty(s_blurAtomName, this);
    }
    connect(KWin::effects, &KWin::EffectsHandler::propertyNotify, this, &Frost::slotPropertyNotify);
    connect(KWin::effects, &KWin::EffectsHandler::xcbConnectionChanged, this, [this]() {
        m_netWmBlurRegion = KWin::effects->announceSupportProperty(s_blurAtomName, this);
    });
#endif

    loadShaders();
}

Frost::~Frost() = default;

bool Frost::supported()
{
    // WHY delegate to the base class rather than reimplementing the GL
    // feature check: OffscreenEffect::supported() already answers exactly
    // the question this effect needs answered (can a real offscreen
    // GL/shader pipeline run at all) -- reimplementing it would duplicate
    // KWin's own platform-capability logic instead of reusing it, and risks
    // getting out of step with it on a future KWin update.
    return KWin::OffscreenEffect::supported();
}

int Frost::requestedEffectChainPosition() const
{
    // See this method's own docstring in frost.h for the full, source-traced
    // reasoning and the live evidence. Blur's confirmed value is 20 (blur.h);
    // Frost must be HIGHER so Blur draws the frosted backdrop onto the real
    // render target before Frost composites the window over it. 30 stays below
    // slidingpopups (40, slidingpopups.h at the pinned tag), so Frost's capture
    // still includes the popup slide animation's own drawWindow() step exactly
    // as it did before.
    return 30;
}

void Frost::loadShaders()
{
    // THE REAL MATERIAL SHADER -- replaces the former DIAGNOSTIC ONLY 50% red
    // tint (which already answered the class docstring's chain-position
    // question; see frost.h's git history / the V4 investigation notes for
    // that shader and what it proved). frost_shader.h's own header comment
    // documents every uniform this shader declares and where its real value
    // comes from; frost.h's apply() docstring documents the math itself and
    // the (source-cited) decisions this method's own body below depends on
    // (why windowSize needs no uniform here, why the noise texture is Frost's
    // own, why these material.* uniforms are set ONCE here rather than every
    // frame in apply()).
    //
    // Traits (MapTexture | Modulate) and the empty vertex-source argument
    // (ShaderManager generates the real one for these traits, confirmed at
    // src/opengl/base.vert, fetched at the pinned tag) are unchanged from the
    // former diagnostic shader -- only the fragment source itself changed.
    std::unique_ptr<KWin::GLShader> shader = KWin::ShaderManager::instance()->generateCustomShader(
        KWin::ShaderTrait::MapTexture | KWin::ShaderTrait::Modulate, QByteArray(),
        QByteArray(Kuura::kFrostFragmentShaderSource));
    if (!shader) {
        // Mirrors this method's own original placeholder contract: leave
        // m_shader null (safe-disabled) rather than pretend a broken shader
        // "succeeded" -- apply()/updateWindowState() both check for this
        // before binding anything to a window.
        return;
    }

    // The noise texture must exist before the noiseSampler uniform below is
    // fixed to a texture unit -- see generateNoiseTexture()'s own docstring in
    // frost.h for why this is a one-time, not per-frame, upload.
    if (!generateNoiseTexture()) {
        return;
    }

    // Upload the window shader's material.* constants (design/tokens.json, via the
    // package-build-time generated <tokens.h>, see this file's own top-of-file
    // include comment) and fix both sampler uniforms to their real texture
    // units, ONCE, right after linking. See frost.h's apply() docstring
    // ("FLAGGED, NOT SILENTLY WORKED AROUND") for the full, cited reasoning on
    // why this cannot instead happen per-frame in apply(): GLShader::setUniform()
    // is a bare glUniform*() call (opengl/glshader.cpp), which OpenGL applies to
    // whichever program is CURRENTLY BOUND -- pushShader()/popShader() (the same
    // idiom plugins/blur/blur.cpp uses for its own custom shaders' uniforms)
    // makes that true for exactly the duration of these calls, and these five
    // values never change at runtime, so doing this once is strictly correct
    // AND cheaper than repeating it on every composited frame.
    KWin::ShaderManager::instance()->pushShader(shader.get());
    shader->setUniform("sampler", 0);
    shader->setUniform("noiseSampler", 1);
    shader->setUniform("edgeHighlightWidth", Kuura::Tokens::kMaterialEdgeHighlightWidth);
    shader->setUniform("edgeHighlightOpacity", Kuura::Tokens::kMaterialEdgeHighlightOpacity);
    shader->setUniform("noiseAmount", Kuura::Tokens::kMaterialNoise);
    // Light-surface rim (frost_shader.h, "LIGHT-SURFACE RIM"):
    // material.edge_highlight.light_* tokens.
    shader->setUniform("lightRimOpacity", Kuura::Tokens::kMaterialEdgeHighlightLightHairlineOpacity);
    shader->setUniform("lightRimWidth", Kuura::Tokens::kMaterialEdgeHighlightLightHairlineWidth);
    shader->setUniform("lightRimLumaLow", Kuura::Tokens::kMaterialEdgeHighlightLightLumaLow);
    shader->setUniform("lightRimLumaHigh", Kuura::Tokens::kMaterialEdgeHighlightLightLumaHigh);
    // WHY the explicit static_cast<float>: GLTexture::width()/height() return
    // `int` (opengl/gltexture.h) -- an implicit int-to-float argument here
    // would trip cppcoreguidelines-narrowing-conversions (enabled in this
    // project's .clang-tidy), even though no real precision loss can occur
    // for a texture this small.
    shader->setUniform("noiseTextureSize",
                        QVector2D(static_cast<float>(m_noiseTexture->width()), static_cast<float>(m_noiseTexture->height())));
    KWin::ShaderManager::instance()->popShader();

    m_shader = std::move(shader);

    // Backdrop refraction pass (drawWindow()). MapTexture only: it samples
    // Frost's backdrop copy and writes it back unmodulated (no opacity or
    // brightness applies to the backdrop; Blur's own on-screen pass already
    // applied the window opacity to what was copied). A link failure only
    // disables backdrop refraction -- the window material above still works.
    std::unique_ptr<KWin::GLShader> backdropShader = KWin::ShaderManager::instance()->generateCustomShader(
        KWin::ShaderTrait::MapTexture, QByteArray(), QByteArray(Kuura::kFrostBackdropFragmentShaderSource));
    if (backdropShader) {
        KWin::ShaderManager::instance()->pushShader(backdropShader.get());
        backdropShader->setUniform("sampler", 0);
        backdropShader->setUniform("refractionStrength", Kuura::Tokens::kMaterialRefractionStrength);
        // WHY the explicit static_cast<float>: material.refraction.edge_falloff
        // is a JSON INTEGER in design/tokens.json (12, not 12.0), so
        // design/generators/cpp_header.py -- preserving the source JSON's type
        // -- generates `kMaterialRefractionEdgeFalloff` as a C++ `int`. Passing
        // it raw would resolve to GLShader::setUniform(const char *, int), i.e.
        // glUniform1i() on a `float` uniform (GL_INVALID_OPERATION, value left
        // unset) -- confirmed from the setUniform() overloads in
        // opengl/glshader.cpp.
        backdropShader->setUniform("refractionEdgeFalloff", static_cast<float>(Kuura::Tokens::kMaterialRefractionEdgeFalloff));
        KWin::ShaderManager::instance()->popShader();
        m_backdropShader = std::move(backdropShader);
    }
}

bool Frost::generateNoiseTexture()
{
    // Mirrors the TECHNIQUE `BlurEffect::ensureNoiseTexture()` uses
    // (plugins/blur/blur.cpp at the pinned tag) -- a tiled grayscale image,
    // GL_NEAREST + GL_REPEAT -- NOT a reference to Blur's own texture object,
    // which is a private member of a different effect instance and cannot be
    // shared (see frost.h's apply() docstring for the full citation). 256x256
    // matches Blur's own real, shipping noise texture's base size; there is no
    // design token for a dither-tile size (an implementation detail of the
    // technique, not a value a theme would tune).
    constexpr int kNoiseTextureSize = 256;
    QImage noiseImage(QSize(kNoiseTextureSize, kNoiseTextureSize), QImage::Format_Grayscale8);

    // WHY a local QRandomGenerator with a FIXED seed: apply()'s docstring asks
    // this method to reuse the noise TECHNIQUE (tiled grayscale image,
    // GL_NEAREST + GL_REPEAT), not Blur's std::rand()/std::srand() source,
    // whose global mutable state is shared with every other caller. The seed
    // is constant because a dither pattern only has to look random, not be
    // unpredictable: with QRandomGenerator::global() (randomly seeded per
    // process) every compositor start drew a different pattern, so two
    // hardware-GL screenshot runs of the same build differed by up to
    // noise * 255 levels on every glass surface and GPU goldens could never
    // match (2026-10-21). A fixed seed makes the pattern identical on every
    // start and every machine.
    constexpr quint32 kNoiseSeed = 0x6B75u;
    QRandomGenerator noiseRng(kNoiseSeed);
    for (int y = 0; y < noiseImage.height(); ++y) {
        // QImage::scanLine() is Qt's own real API for direct pixel access; it
        // returns a raw uchar* by design, with no bounds-checked alternative in
        // QImage itself. A std::span wrapper was tried and rejected: span's own
        // operator[] then trips cppcoreguidelines-pro-bounds-avoid-unchecked-
        // container-access instead (span has no .at()-style checked accessor in
        // the current standard), so it only trades one warning for another
        // without removing any real risk -- the loop bound below (`x <
        // noiseImage.width()`) is the exact same extent scanLine()'s own buffer
        // is guaranteed to hold, by QImage's own contract.
        uchar *line = noiseImage.scanLine(y);
        for (int x = 0; x < noiseImage.width(); ++x) {
            line[x] = static_cast<uchar>(noiseRng.bounded(256)); // NOLINT(cppcoreguidelines-pro-bounds-pointer-arithmetic)
        }
    }

    std::unique_ptr<KWin::GLTexture> texture = KWin::GLTexture::upload(noiseImage);
    if (!texture) {
        return false;
    }
    // GL_NEAREST: dither noise must stay per-texel random, never smoothed by
    // linear filtering (which would visibly blur/average the pattern away).
    // GL_REPEAT: the shader tiles this texture across the whole window via
    // gl_FragCoord (unbounded screen-space coordinates), matching
    // blur/shaders/noise.frag's own real sampling convention (frost_shader.h).
    texture->setFilter(GL_NEAREST);
    texture->setWrapMode(GL_REPEAT);

    m_noiseTexture = std::move(texture);
    return true;
}

void Frost::slotWindowAdded(KWin::EffectWindow *window)
{
    // Mirrors BlurEffect::slotWindowAdded() exactly (blur.cpp at the pinned
    // tag): connect every live-update signal a window's blur-region state can
    // change through, THEN do the initial check. Order matters here only in
    // that the initial updateWindowState() call below must run after these
    // connections exist, not before, so a change that happens to land in the
    // same event-loop turn as window-addition itself is never missed.
    if (KWin::SurfaceInterface *surface = window->surface()) {
        // QMap::operator[]'s ordinary insert-or-update idiom (mirrors
        // BlurEffect::windowBlurChangedConnections's own identical use in
        // blur.cpp), not an unchecked array/pointer index this check's real
        // target (e.g. std::vector, std::span) would flag meaningfully.
        // NOLINTNEXTLINE(cppcoreguidelines-pro-bounds-avoid-unchecked-container-access)
        m_surfaceBlurChangedConnections[window] =
            connect(surface, &KWin::SurfaceInterface::blurChanged, this, [this, window]() {
                updateWindowState(window);
            });
    }
    if (auto *internal = window->internalWindow()) {
        internal->installEventFilter(this);
    }

    setupDecorationConnections(window);
    connect(window, &KWin::EffectWindow::windowDecorationChanged, this, [this, window]() {
        setupDecorationConnections(window);
        updateWindowState(window);
    });

    updateWindowState(window);
}

void Frost::slotWindowDeleted(KWin::EffectWindow *window)
{
    // Only cleans up Frost's OWN bookkeeping (the surface's blurChanged
    // connection) -- OffscreenEffect's base class already auto-unredirects a
    // deleted window via its own EffectsHandler::windowDeleted connection
    // (see offscreeneffect.cpp's setupConnections()/handleWindowDeleted()),
    // which knows nothing about this connection map.
    if (auto it = m_surfaceBlurChangedConnections.find(window); it != m_surfaceBlurChangedConnections.end()) {
        disconnect(*it);
        m_surfaceBlurChangedConnections.erase(it);
    }
    m_glassRects.remove(window);
    m_glassRegions.remove(window);
    dropBackdropCopies(window);
}

void Frost::slotViewRemoved(KWin::RenderView *view)
{
    for (auto &[window, perView] : m_backdropCopies) {
        if (auto it = perView.find(view); it != perView.end()) {
            KWin::effects->makeOpenGLContextCurrent();
            perView.erase(it);
        }
    }
}

void Frost::dropBackdropCopies(KWin::EffectWindow *window)
{
    if (auto it = m_backdropCopies.find(window); it != m_backdropCopies.end()) {
        KWin::effects->makeOpenGLContextCurrent();
        m_backdropCopies.erase(it);
    }
}

void Frost::setupDecorationConnections(KWin::EffectWindow *window)
{
    // Mirrors BlurEffect::setupDecorationConnections() exactly (blur.cpp): a
    // no-op if the window currently has no decoration (every Wayland
    // panel/popup/KRunner surface this test targets never does).
    if (!window->decoration()) {
        return;
    }
    connect(window->decoration(), &KDecoration3::Decoration::blurRegionChanged, this, [this, window]() {
        updateWindowState(window);
    });
}

bool Frost::eventFilter(QObject *watched, QEvent *event)
{
    // Mirrors BlurEffect::eventFilter() exactly (blur.cpp): notices a
    // dynamic "kwin_blur" property arriving (or changing) on an internal Qt
    // window (e.g. a KWin-owned popup) after slotWindowAdded() already
    // installed this filter on it.
    auto *internal = qobject_cast<QWindow *>(watched);
    if (internal && event->type() == QEvent::DynamicPropertyChange) {
        // The standard Qt idiom for narrowing a QEvent after checking its
        // type() (QEvent has no RTTI-friendly public dynamic_cast path this
        // check's dynamic_cast suggestion would actually use); identical
        // static_cast<QDynamicPropertyChangeEvent *> pattern used by
        // BlurEffect::eventFilter() itself in blur.cpp at the pinned tag.
        // NOLINTNEXTLINE(cppcoreguidelines-pro-type-static-cast-downcast)
        auto *propertyChange = static_cast<QDynamicPropertyChangeEvent *>(event);
        if (propertyChange->propertyName() == "kwin_blur") {
            if (KWin::EffectWindow *window = KWin::effects->findWindow(internal)) {
                updateWindowState(window);
            }
        }
    }
    return false;
}

#if KWIN_BUILD_X11
void Frost::slotPropertyNotify(KWin::EffectWindow *window, long atom)
{
    if (window && atom == m_netWmBlurRegion && m_netWmBlurRegion != XCB_ATOM_NONE) {
        updateWindowState(window);
    }
}
#endif

std::optional<KWin::RegionF> Frost::glassRegion(KWin::EffectWindow *window) const
{
    // Mirrors BlurEffect::updateBlurRegion() + BlurEffect::blurRegion()
    // (blur.cpp at the pinned tag) source by source, so Frost's glass rect is
    // exactly the area Blur frosts -- the two effects must agree on WHERE the
    // glass is, or the highlight would float off the blurred shape and the
    // backdrop refraction would write outside it. The window shader uses
    // only the bounding box (rounded corners inside it are handled by the
    // captured texture's own alpha, frost_shader.h); refractBackdrop() clips
    // to the full region.
    std::optional<KWin::RegionF> content;
    std::optional<KWin::RegionF> frame;

#if KWIN_BUILD_X11
    if (m_netWmBlurRegion != XCB_ATOM_NONE) {
        if (auto *x11Window = qobject_cast<KWin::X11Window *>(window->window())) {
            KWin::Xcb::Property wmBlurRegionProperty(
                false, x11Window->window(), m_netWmBlurRegion, XCB_ATOM_CARDINAL, 0, 32768);
            if (const auto cardinals = wmBlurRegionProperty.array<uint32_t>()) {
                // Same encoding Blur decodes: 0 or 1 cardinals = "the whole
                // window"; otherwise (x, y, w, h) quadruples in X native units.
                if (cardinals->size() == 0 || cardinals->size() == 1) {
                    content = KWin::RegionF();
                } else if (cardinals->size() % 4 == 0) {
                    KWin::RegionF region;
                    for (size_t i = 0; i + 3 < cardinals->size(); i += 4) {
                        const int x = static_cast<int>((*cardinals)[i]);
                        const int y = static_cast<int>((*cardinals)[i + 1]);
                        const int w = static_cast<int>((*cardinals)[i + 2]);
                        const int h = static_cast<int>((*cardinals)[i + 3]);
                        region += KWin::Xcb::fromXNative(KWin::Rect(x, y, w, h));
                    }
                    content = region;
                }
            }
        }
    }
#endif

    if (KWin::SurfaceInterface *surface = window->surface()) {
        if (!surface->blurRegion().isEmpty()) {
            content = surface->blurRegion();
        }
    }

    if (auto *internal = window->internalWindow()) {
        const QVariant property = internal->property("kwin_blur");
        if (property.isValid()) {
            content = property.value<KWin::RegionF>();
        }
    }

    if (window->decorationHasAlpha() && window->decoration() && !window->decoration()->blurRegion().isNull()) {
        // Blur's decorationBlurRegion(): the decoration's own blur region,
        // limited to the decoration area (frame minus contents).
        const KWin::RegionF decorationRegion = KWin::RegionF(window->decoration()->rect()) - window->contentsRect();
        frame = decorationRegion.intersected(KWin::RegionF(window->decoration()->blurRegion()));
    }

    if (!content.has_value() && !frame.has_value()) {
        return std::nullopt;
    }

    // Blur's blurRegion(): an EMPTY content region means "the whole contents
    // rect"; a non-empty one is in contents-local coordinates and is clipped
    // to the contents rect. The result is in frame-local logical coordinates.
    KWin::RegionF region;
    if (content.has_value()) {
        const KWin::RectF contentsRect = window->contentsRect();
        if (content->isEmpty()) {
            region = contentsRect;
        } else {
            region = content->translated(contentsRect.topLeft()) & contentsRect;
        }
    }
    if (frame.has_value()) {
        region += frame.value();
    }
    return region;
}

void Frost::updateWindowState(KWin::EffectWindow *window)
{
    // A window wants the glass material exactly when Blur would blur it (see
    // glassBoundingRect()); the rect itself is cached here, on the change
    // signals, rather than recomputed every frame in apply(), because the X11
    // branch is a server round-trip.
    const std::optional<KWin::RegionF> region = glassRegion(window);

    if (region.has_value()) {
        m_glassRects.insert(window, QRectF(region->boundingRect()));
        m_glassRegions.insert(window, *region);
        redirect(window);
        setShader(window, m_shader.get());
        // DELIBERATELY NOT setting WindowForceBlurRole any more (an earlier
        // version did): with Frost AFTER Blur in the chain (see
        // requestedEffectChainPosition()), Frost's own capture never reaches
        // Blur at all, so the role would only have the side effect of forcing
        // Blur on for this window during fullscreen effects and transformed
        // paints, which Blur deliberately refuses (blur.cpp's shouldBlur()).
        // Frost also must not clear the role on unredirect: another effect may
        // own it.
    } else {
        m_glassRects.remove(window);
        m_glassRegions.remove(window);
        dropBackdropCopies(window);
        unredirect(window);
    }
}

void Frost::apply(KWin::EffectWindow *window, int mask, KWin::WindowPaintData &data, KWin::WindowQuadList &quads)
{
    Q_UNUSED(mask)
    Q_UNUSED(data)
    Q_UNUSED(quads)

    if (!m_shader || !m_noiseTexture) {
        return;
    }

    // `data`/`quads` are deliberately left untouched: the refraction offset and
    // specular highlight are pure per-pixel fragment-shader math
    // (frost_shader.h), not a geometry or paint-data change.

    // ---- Per-window glass rect (frost_shader.h's `glassRect` uniform) ----
    // The captured texture spans the window's EXPANDED geometry (shadow
    // included), snapped with the output scale exactly as
    // OffscreenData::maybeRender() does; the cached glass rect is frame-local
    // logical. Translate it into the texture's own device-pixel grid.
    QVector4D glassRectUniform(0.0F, 0.0F, 0.0F, 0.0F);
    const auto glassIt = m_glassRects.constFind(window);
    if (glassIt != m_glassRects.constEnd() && window->screen()) {
        const qreal scale = window->screen()->scale();
        const QRectF expanded = KWin::snapToPixels(QRectF(window->expandedGeometry()), scale);
        const QRectF frameGeometry = KWin::snapToPixels(QRectF(window->frameGeometry()), scale);
        const QPointF frameOffset = frameGeometry.topLeft() - expanded.topLeft();
        const QRectF glass = glassIt->translated(frameOffset);
        glassRectUniform = QVector4D(static_cast<float>(glass.x() * scale), static_cast<float>(glass.y() * scale),
                                     static_cast<float>(glass.width() * scale), static_cast<float>(glass.height() * scale));
    }
    // WHY push/pop here although apply() runs before OffscreenData::paint()
    // binds the shader: GLShader::setUniform() is a bare glUniform*() call that
    // targets the CURRENTLY BOUND program, so binding Frost's program for the
    // duration of the call (the same idiom blur.cpp uses for its own passes) is
    // what makes it land in Frost's program. Uniform values are program state:
    // they survive the unbind and are still there when paint() binds the same
    // program a moment later for THIS window, and apply() runs again for every
    // window before its own paint(), so each window gets its own rect.
    KWin::ShaderManager::instance()->pushShader(m_shader.get());
    m_shader->setUniform("glassRect", glassRectUniform);
    KWin::ShaderManager::instance()->popShader();

    // ---- Noise texture binding (texture unit 1) ----
    // A GL texture BINDING, not a uniform value: glBindTexture() only cares
    // about the currently ACTIVE unit, not which program is bound, so it is
    // safe here before paint()'s own ShaderBinder. GLTexture::bind()
    // (opengl/gltexture.cpp at the pinned tag) never calls glActiveTexture()
    // itself, so restoring unit 0 as active before returning keeps paint()'s
    // `m_texture->bind()` on unit 0 while unit 1 still holds the noise texture
    // the shader's noiseSampler (fixed to 1 at link time) reads.
    glActiveTexture(GL_TEXTURE1);
    m_noiseTexture->bind();
    glActiveTexture(GL_TEXTURE0);
}

void Frost::prePaintScreen(KWin::ScreenPrePaintData &data)
{
    // Mirrors BlurEffect::prePaintScreen() (blur.cpp): remember the view, then
    // forward down the chain.
    m_currentView = data.view;
    KWin::effects->prePaintScreen(data);
}

void Frost::drawWindow(const KWin::RenderTarget &renderTarget, const KWin::RenderViewport &viewport, KWin::EffectWindow *window,
                       int mask, const KWin::Region &deviceRegion, KWin::WindowPaintData &data)
{
    // Order is the whole point (see the docstring in frost.h): Blur's output
    // is on renderTarget now, the window is not yet. Refract first, then let
    // the base class composite the window over the refracted backdrop.
    refractBackdrop(renderTarget, viewport, window, mask, deviceRegion, data);
    KWin::OffscreenEffect::drawWindow(renderTarget, viewport, window, mask, deviceRegion, data);
}

bool Frost::backdropIsBlurred(const KWin::EffectWindow *window, int mask, const KWin::WindowPaintData &data) const
{
    // BlurEffect::isActive(): Blur does not run while the screen is locked.
    // "blur" is Blur's plugin id (its metadata.json), the name
    // EffectsHandler::isEffectLoaded() compares against.
    if (KWin::effects->isScreenLocked() || !KWin::effects->isEffectLoaded(QStringLiteral("blur"))) {
        return false;
    }
    // The rest is BlurEffect::shouldBlur() verbatim in logic, including its
    // "scaled" test requiring BOTH axes to differ from 1 -- Frost must refract
    // exactly when Blur blurred, not when it "should have".
    const bool forced = window->data(KWin::WindowForceBlurRole).toBool();
    if (KWin::effects->activeFullScreenEffect() && !forced) {
        return false;
    }
    if (window->isDesktop()) {
        return false;
    }
    const bool scaled = !qFuzzyCompare(data.xScale(), 1.0) && !qFuzzyCompare(data.yScale(), 1.0);
    const bool translated = !qFuzzyIsNull(data.xTranslation()) || !qFuzzyIsNull(data.yTranslation());
    if ((scaled || translated || (mask & KWin::Effect::PAINT_WINDOW_TRANSFORMED) != 0) && !forced) {
        return false;
    }
    // Blur draws its backdrop with modulation opacity^2 (blur.cpp); at zero
    // there is no frosted backdrop to refract.
    return window->opacity() * data.opacity() > 0.0;
}

void Frost::refractBackdrop(const KWin::RenderTarget &renderTarget, const KWin::RenderViewport &viewport, KWin::EffectWindow *window,
                            int mask, const KWin::Region &deviceRegion, const KWin::WindowPaintData &data)
{
    if (!m_backdropShader) {
        return;
    }
    const auto regionIt = m_glassRegions.constFind(window);
    if (regionIt == m_glassRegions.constEnd() || !backdropIsBlurred(window, mask, data)) {
        return;
    }

    // ---- Glass shape in global logical coordinates: BlurEffect::blur()'s
    // exact transform (scale, then translation, then window position), so a
    // sliding popup's band moves with Blur's backdrop. ----
    KWin::RegionF shape = *regionIt;
    if (!qFuzzyCompare(data.xScale(), 1.0) || !qFuzzyCompare(data.yScale(), 1.0)) {
        shape.scale(data.xScale(), data.yScale());
    }
    if (!qFuzzyIsNull(data.xTranslation()) || !qFuzzyIsNull(data.yTranslation())) {
        shape.translate(data.xTranslation(), data.yTranslation());
    }
    shape.translate(window->pos());

    const KWin::Rect backgroundRect = shape.boundingRect().rounded();
    const qreal scale = viewport.scale();
    const KWin::Rect scaledBackgroundRect = backgroundRect.scaled(scale).rounded();
    const KWin::Rect deviceBackgroundRect = viewport.mapToDeviceCoordinates(backgroundRect).rounded();
    if (scaledBackgroundRect.isEmpty()) {
        return;
    }

    // ---- The band that can change: within edge_falloff of the bbox edge the
    // displacement is non-zero; +1 px covers the falloff's last fractional
    // pixel. Everything here is bbox-local DEVICE pixels, top-left origin,
    // which is the coordinate frame Blur's on-screen pass uses too. ----
    const float falloff = static_cast<float>(Kuura::Tokens::kMaterialRefractionEdgeFalloff);
    const int bandDevice = static_cast<int>(std::ceil(falloff)) + 1;
    const KWin::Rect localDeviceRect(0, 0, scaledBackgroundRect.width(), scaledBackgroundRect.height());
    KWin::Region band(localDeviceRect);
    if (const KWin::Rect inner = localDeviceRect.adjusted(bandDevice, bandDevice, -bandDevice, -bandDevice); !inner.isEmpty()) {
        band -= inner;
    }
    // Only inside the blur shape (never in a rounded popup's cut-off corner,
    // where the screen shows the sharp desktop) and only inside the repaint.
    KWin::Region shapeDevice;
    for (const KWin::RectF &rect : shape.rects()) {
        shapeDevice |= rect.translated(-backgroundRect.topLeft()).scaled(scale).rounded();
    }
    KWin::Region effective = shapeDevice & band;
    if (deviceRegion != KWin::Region::infinite()) {
        effective &= deviceRegion.translated(-deviceBackgroundRect.topLeft());
    }
    if (effective.isEmpty()) {
        return;
    }

    // ---- Per-window, per-view backdrop copy (see BackdropCopy in frost.h).
    // Same format rule as BlurEffect::blur(): match the target's own format so
    // the round trip is lossless (e.g. a 10-bit or float HDR target). ----
    BackdropCopy &copy = m_backdropCopies[window][m_currentView];
    const GLenum textureFormat = renderTarget.texture() ? renderTarget.texture()->internalFormat() : GL_RGBA8;
    const QSize copySize(scaledBackgroundRect.width(), scaledBackgroundRect.height());
    bool fresh = false;
    if (!copy.texture || copy.texture->size() != copySize || copy.texture->internalFormat() != textureFormat) {
        copy.framebuffer.reset();
        copy.texture = KWin::GLTexture::allocate(textureFormat, copySize);
        if (!copy.texture) {
            return;
        }
        copy.texture->setFilter(GL_LINEAR);
        copy.texture->setWrapMode(GL_CLAMP_TO_EDGE);
        copy.framebuffer = std::make_unique<KWin::GLFramebuffer>(copy.texture.get());
        if (!copy.framebuffer->valid()) {
            copy.framebuffer.reset();
            copy.texture.reset();
            return;
        }
        fresh = true;
    }

    // ---- Read Blur's output: the repainted part of the band only, exactly
    // BlurEffect::blur()'s "Fetch the pixels behind the shape" loop. Logical
    // source rects, device destination rects (this copy is device-sized,
    // unlike Blur's logical-sized one, so the refracted band keeps full
    // resolution at scale > 1). The band is widened by one more logical pixel
    // than it is drawn: an inward sample at the band's inner edge reads up to
    // one texel further in. ----
    const int bandLogical = static_cast<int>(std::ceil((bandDevice + 1) / scale));
    KWin::Region bandLogicalRegion(backgroundRect);
    if (const KWin::Rect inner = backgroundRect.adjusted(bandLogical, bandLogical, -bandLogical, -bandLogical); !inner.isEmpty()) {
        bandLogicalRegion -= inner;
    }
    const KWin::Region dirtyRegion = viewport.mapFromDeviceCoordinatesContained(deviceRegion) & bandLogicalRegion;
    for (const KWin::Rect &dirtyRect : dirtyRegion.rects()) {
        copy.framebuffer->blitFromRenderTarget(renderTarget, viewport, dirtyRect,
                                               dirtyRect.translated(-backgroundRect.topLeft()).scaled(scale).rounded());
    }
    // A freshly allocated copy holds nothing outside what was just blitted.
    // Sampling it there would write undefined texels into the backdrop, so
    // draw only if this frame repainted the whole band -- the normal case,
    // since a new copy follows a map or resize, and both damage the whole
    // window. Otherwise the band is skipped for one frame (no refraction,
    // never garbage).
    if (fresh && !(bandLogicalRegion - dirtyRegion).isEmpty()) {
        return;
    }

    // ---- Draw the band back, displaced. Vertex layout, texcoord convention
    // (v = 1 - y / height) and projection (viewport projection translated to
    // the scaled bbox) are those of BlurEffect::blur()'s on-screen pass. ----
    KWin::GLVertexBuffer *vbo = KWin::GLVertexBuffer::streamingBuffer();
    vbo->reset();
    vbo->setAttribLayout(std::span(KWin::GLVertexBuffer::GLVertex2DLayout), sizeof(KWin::GLVertex2D));
    const int vertexCount = static_cast<int>(effective.rects().size()) * 6;
    const auto mapped = vbo->map<KWin::GLVertex2D>(static_cast<size_t>(vertexCount));
    if (!mapped) {
        return;
    }
    {
        auto vertices = *mapped;
        size_t index = 0;
        const auto width = static_cast<float>(copySize.width());
        const auto height = static_cast<float>(copySize.height());
        for (const KWin::Rect &rect : effective.rects()) {
            const auto x0 = static_cast<float>(rect.x());
            const auto y0 = static_cast<float>(rect.y());
            const auto x1 = static_cast<float>(rect.x() + rect.width());
            const auto y1 = static_cast<float>(rect.y() + rect.height());
            const auto vertex = [width, height](float x, float y) {
                return KWin::GLVertex2D{.position = QVector2D(x, y), .texcoord = QVector2D(x / width, 1.0F - y / height)};
            };
            // Two triangles per rect, same winding as blur.cpp.
            vertices[index++] = vertex(x0, y0);
            vertices[index++] = vertex(x1, y1);
            vertices[index++] = vertex(x0, y1);
            vertices[index++] = vertex(x0, y0);
            vertices[index++] = vertex(x1, y0);
            vertices[index++] = vertex(x1, y1);
        }
    }
    vbo->unmap();
    vbo->bindArrays();

    KWin::ShaderManager::instance()->pushShader(m_backdropShader.get());
    QMatrix4x4 projectionMatrix = viewport.projectionMatrix();
    projectionMatrix.translate(static_cast<float>(scaledBackgroundRect.x()), static_cast<float>(scaledBackgroundRect.y()));
    m_backdropShader->setUniform(KWin::GLShader::Mat4Uniform::ModelViewProjectionMatrix, projectionMatrix);
    m_backdropShader->setUniform("backdropSize", QVector2D(static_cast<float>(copySize.width()), static_cast<float>(copySize.height())));

    // Blending OFF: the band REPLACES the backdrop with its displaced copy
    // (alpha included; see the shader's own comment on premultiplication).
    glDisable(GL_BLEND);
    glActiveTexture(GL_TEXTURE0);
    copy.texture->bind();
    vbo->draw(GL_TRIANGLES, 0, vertexCount);
    copy.texture->unbind();

    KWin::ShaderManager::instance()->popShader();
    vbo->unbindArrays();
}

} // namespace Kuura
