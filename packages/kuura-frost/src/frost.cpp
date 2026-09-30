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

// The generated tokens.h below is a package-build-time artifact (see
// design/generators/cpp_header.py and packages/kuura-frost/PKGBUILD's build()),
// not a checked-in source file -- packages/kuura-frost/CMakeLists.txt adds its
// real, generated location (<package dir>/generated/cpp/) to this target's
// include path. This is the ONE place design/tokens.json's material.* numbers
// reach this file; nothing below hand-copies a tokens.json value as a literal
// (frost.h's own class docstring explicitly forbids that).
#include <tokens.h>

#include <QImage>
#include <QRandomGenerator>
#include <QVector2D>

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
    // reasoning. Blur's confirmed value is 20 (blur.h); Frost must be LOWER.
    // 10 leaves headroom on both sides (nothing else in this project's
    // shipped effect set currently claims a position below 20) without
    // crowding position 0.
    return 10;
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

    // Upload the five material.* constants (design/tokens.json, via the
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
    // WHY the explicit static_cast<float>: material.refraction.edge_falloff is
    // a JSON INTEGER in design/tokens.json (12, not 12.0), so
    // design/generators/cpp_header.py -- correctly, since it preserves the
    // source JSON's own type rather than guessing an intended one -- generates
    // `kMaterialRefractionEdgeFalloff` as a C++ `int`. The shader declares
    // `refractionEdgeFalloff` as `float` (frost_shader.h). Passing the raw int
    // here would resolve to GLShader::setUniform(const char *, int), which
    // calls glUniform1i() -- a real OpenGL type mismatch against a `float`
    // uniform (GL_INVALID_OPERATION, value left unset) -- confirmed by reading
    // every setUniform() overload in opengl/glshader.cpp, not assumed.
    shader->setUniform("refractionStrength", Kuura::Tokens::kMaterialRefractionStrength);
    shader->setUniform("refractionEdgeFalloff", static_cast<float>(Kuura::Tokens::kMaterialRefractionEdgeFalloff));
    shader->setUniform("edgeHighlightWidth", Kuura::Tokens::kMaterialEdgeHighlightWidth);
    shader->setUniform("edgeHighlightOpacity", Kuura::Tokens::kMaterialEdgeHighlightOpacity);
    shader->setUniform("noiseAmount", Kuura::Tokens::kMaterialNoise);
    // WHY the explicit static_cast<float>: GLTexture::width()/height() return
    // `int` (opengl/gltexture.h) -- an implicit int-to-float argument here
    // would trip cppcoreguidelines-narrowing-conversions (enabled in this
    // project's .clang-tidy), even though no real precision loss can occur
    // for a texture this small.
    shader->setUniform("noiseTextureSize",
                        QVector2D(static_cast<float>(m_noiseTexture->width()), static_cast<float>(m_noiseTexture->height())));
    KWin::ShaderManager::instance()->popShader();

    m_shader = std::move(shader);
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

    // WHY QRandomGenerator rather than literally mirroring BlurEffect's own
    // std::rand()/std::srand() call: apply()'s docstring asks this method to
    // reuse the noise TECHNIQUE (tiled grayscale image, GL_NEAREST + GL_REPEAT),
    // not its exact RNG source. QRandomGenerator::global() is already seeded,
    // thread-safe, and has none of std::rand()/std::srand()'s global-mutable-
    // state re-entrancy concerns -- a strictly better choice for newly written
    // code generating a one-shot, non-cryptographic dither pattern.
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
            line[x] = static_cast<uchar>(QRandomGenerator::global()->bounded(256)); // NOLINT(cppcoreguidelines-pro-bounds-pointer-arithmetic)
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

void Frost::updateWindowState(KWin::EffectWindow *window)
{
    // Detection order mirrors BlurEffect::updateBlurRegion() exactly (blur.cpp
    // at the pinned tag), per frost.h's class docstring -- Frost does not
    // store the region's geometry, only whether a qualifying region exists
    // from ANY of these sources.
    bool wantsGlass = false;

#if KWIN_BUILD_X11
    if (m_netWmBlurRegion != XCB_ATOM_NONE) {
        if (auto *x11Window = qobject_cast<KWin::X11Window *>(window->window())) {
            KWin::Xcb::Property wmBlurRegionProperty(
                false, x11Window->window(), m_netWmBlurRegion, XCB_ATOM_CARDINAL, 0, 32768);
            // The property's mere PRESENCE (any array at all, even
            // zero-length -- "blur the whole window") is the signal Frost
            // cares about; unlike Blur, it never needs the actual rectangles.
            if (wmBlurRegionProperty.array<uint32_t>()) {
                wantsGlass = true;
            }
        }
    }
#endif

    if (!wantsGlass) {
        if (KWin::SurfaceInterface *surface = window->surface()) {
            wantsGlass = !surface->blurRegion().isEmpty();
        }
    }

    if (!wantsGlass) {
        if (auto *internal = window->internalWindow()) {
            wantsGlass = internal->property("kwin_blur").isValid();
        }
    }

    if (!wantsGlass && window->decorationHasAlpha() && window->decoration()
        && !window->decoration()->blurRegion().isNull()) {
        wantsGlass = true;
    }

    if (wantsGlass) {
        redirect(window);
        setShader(window, m_shader.get());
        // RESOLVED (see requestedEffectChainPosition()'s own docstring for
        // the full trace): OffscreenData::maybeRender() -- the base class
        // method that actually captures this window into Frost's FBO --
        // always passes the PAINT_WINDOW_TRANSFORMED mask (confirmed at
        // offscreeneffect.cpp), which makes BlurEffect::shouldBlur() refuse
        // to blur UNLESS this window's WindowForceBlurRole data is true
        // (confirmed at blur.cpp's shouldBlur(); the role itself is
        // documented at effecthandler.h's DataRole enum as "for fullscreen
        // effects to enforce blurring of windows" -- Frost's own capture is
        // exactly that same kind of case). CrossFadeEffect (also in
        // offscreeneffect.cpp) deliberately CLEARS this same role around its
        // own capture, for the opposite reason (it does NOT want blur baked
        // into its snapshot) -- confirming the flag is real and that
        // inclusion is the default this project's design wants Frost to keep,
        // not fight.
        window->setData(KWin::WindowForceBlurRole, true);
    } else {
        window->setData(KWin::WindowForceBlurRole, QVariant());
        unredirect(window);
    }
}

void Frost::apply(KWin::EffectWindow *window, int mask, KWin::WindowPaintData &data, KWin::WindowQuadList &quads)
{
    Q_UNUSED(window)
    Q_UNUSED(mask)
    Q_UNUSED(data)
    Q_UNUSED(quads)

    if (!m_shader || !m_noiseTexture) {
        return;
    }

    // `data`/`quads` are deliberately left untouched: the refraction offset and
    // specular highlight are pure per-pixel fragment-shader math
    // (frost_shader.h), not a geometry or paint-data change -- this is the
    // now-determined answer to frost.h's own apply() docstring question
    // ("unmodified unless the refraction offset needs to be expressed as a
    // geometry change... to be determined empirically against the real API").
    //
    // The ONLY real per-frame work left for apply(): rebind Frost's OWN noise
    // texture to texture unit 1 before OffscreenData::paint() (base class,
    // called right after this method returns -- offscreeneffect.cpp's
    // OffscreenEffect::drawWindow(): `apply(...); maybeRender(); paint();`)
    // draws this window with Frost's shader. See frost.h's apply() docstring
    // ("FLAGGED, NOT SILENTLY WORKED AROUND") for why the UNIFORM VALUES
    // themselves (including "the noise sampler reads unit 1") are fixed once in
    // loadShaders() instead of here: this is a GL texture BINDING, not a
    // uniform value, and glBindTexture() only cares about the currently ACTIVE
    // unit, not which shader program happens to be bound -- so, unlike
    // setUniform(), it is safe to call from apply(), before paint()'s own
    // ShaderBinder binds Frost's shader.
    //
    // WHY this is also safe against paint()'s own later `m_texture->bind()`:
    // GLTexture::bind() (opengl/gltexture.cpp, fetched at the pinned tag) never
    // calls glActiveTexture() itself -- it only binds to whichever unit is
    // already active. Restoring unit 0 as active before returning (without
    // unbinding unit 1's own texture -- "active" only controls which unit the
    // NEXT bind/parameter call affects) is what keeps that assumption intact:
    // paint()'s `m_texture->bind()` lands on unit 0 as it always has, while
    // unit 1 still holds Frost's noise texture for the shader's noiseSampler
    // uniform (fixed to 1 at link time) to read from. Nothing in the real,
    // fetched rendering path this window's capture/paint touches (blur.cpp,
    // glshader.cpp, gltexture.cpp, offscreeneffect.cpp) calls glActiveTexture()
    // at all, so no other code silently steals unit 1 in between either.
    glActiveTexture(GL_TEXTURE1);
    m_noiseTexture->bind();
    glActiveTexture(GL_TEXTURE0);
}

} // namespace Kuura
