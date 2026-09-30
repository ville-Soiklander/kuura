#include "frost.h"

// Confirmed live at /usr/include/kwin/opengl/glshadermanager.h and
// /usr/include/kwin/opengl/glshader.h against the pinned Arch snapshot's kwin
// package (V4 investigation notes).
#include <opengl/glshader.h>
#include <opengl/glshadermanager.h>
#include <effect/effecthandler.h>
#include <effect/effectwindow.h>

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
    // DIAGNOSTIC ONLY -- see the commit/PR that introduces Frost's real
    // material shader (refraction/specular-highlight/noise, per frost.h's
    // class docstring) for the finished replacement. This exists solely to
    // answer the class docstring's "STILL OPEN" chain-position question
    // empirically, per the working brief: it blends whatever texture Frost's
    // OffscreenEffect base class actually captures toward solid red at 50%
    // strength, so a live guest screenshot shows unambiguously whether Blur's
    // blurred backdrop is already present in it (blurred-and-red = yes) or
    // not (sharp-and-red = no).
    //
    // Traits requested: MapTexture (sample the redirected texture) and
    // Modulate (so OffscreenData::paint()'s own opacity/brightness handling --
    // which unconditionally calls
    // setUniform(GLShader::Vec4Uniform::ModulationConstant, ...) regardless of
    // which shader is bound, confirmed at opengl/offscreeneffect.cpp -- still
    // has a real `modulation` uniform to write into). Deliberately WITHOUT
    // AdjustSaturation/TransformColorspace: the real shader will eventually
    // want both, but they pull in saturation.glsl/colormanagement.glsl
    // #include complexity this throwaway tint does not need. Skipping them is
    // safe, not just convenient: GLShader::setUniform() silently no-ops for a
    // uniform this fragment source does not declare -- confirmed at
    // opengl/glshader.cpp's own setUniform(int location, ...) overloads,
    // every one of which guards its glUniform*() call with `if (location >=
    // 0)`, and resolveLocations() stores -1 for a name glGetUniformLocation()
    // does not find in the linked program.
    //
    // The vertex shader argument is left empty so ShaderManager generates the
    // correct one for these same traits (opengl/base.vert at the pinned tag:
    // declares `in vec4 position`/`texcoord`, `out vec2 texcoord0`, `uniform
    // mat4 modelViewProjectionMatrix`) -- only the fragment stage is custom.
    // `#version 140` is first, matching opengl/base.frag's own convention,
    // because ShaderManager::generateCustomShader() prepends its `#define
    // TRAIT_...` lines to whatever source it is given (confirmed at
    // opengl/glshadermanager.cpp's generateCustomShader()) -- ahead of
    // `#version` even for KWin's OWN generated shaders, so this already-
    // shipping, already-working ordering is reused rather than "fixed".
    static const QByteArray fragmentSource = QByteArrayLiteral(
        "#version 140\n"
        "uniform sampler2D sampler;\n"
        "in vec2 texcoord0;\n"
        "uniform vec4 modulation;\n"
        "out vec4 fragColor;\n"
        "void main(void)\n"
        "{\n"
        "    vec4 sampled = texture(sampler, texcoord0);\n"
        "    // DIAGNOSTIC ONLY: 50%% blend toward solid red, alpha preserved\n"
        "    // so a translucent panel/popup still shows through to whatever\n"
        "    // is behind it -- that visibility is the whole point of the test.\n"
        "    vec3 tinted = mix(sampled.rgb, vec3(1.0, 0.0, 0.0), 0.5);\n"
        "    fragColor = vec4(tinted, sampled.a) * modulation;\n"
        "}\n");

    std::unique_ptr<KWin::GLShader> shader = KWin::ShaderManager::instance()->generateCustomShader(
        KWin::ShaderTrait::MapTexture | KWin::ShaderTrait::Modulate, QByteArray(), fragmentSource);
    if (!shader) {
        // Mirrors this method's own original placeholder contract: leave
        // m_shader null (safe-disabled) rather than pretend a broken shader
        // "succeeded" -- apply()/updateWindowState() both check for this
        // before binding anything to a window.
        return;
    }
    m_shader = std::move(shader);
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
    if (!m_shader) {
        return;
    }
    // PLACEHOLDER: the real refraction UV-offset and specular-highlight
    // geometry/paint-data changes are not yet implemented (see frost.h's
    // class docstring for the real, confirmed apply() contract this must
    // eventually satisfy) -- this bounded change only needed to prove the
    // chain-position/texture-capture question, which the DIAGNOSTIC ONLY tint
    // shader bound in loadShaders()/updateWindowState() already answers by
    // itself, with no geometry or paint-data change required. Left as a safe
    // no-op rather than guessed at.
    Q_UNUSED(window)
    Q_UNUSED(mask)
    Q_UNUSED(data)
    Q_UNUSED(quads)
}

} // namespace Kuura
