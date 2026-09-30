#pragma once

// Confirmed live at /usr/include/kwin/effect/offscreeneffect.h against the
// pinned Arch snapshot's kwin package (V4 investigation notes) -- NOT the
// older kwineffects/ path an older KWin version used.
#include <effect/offscreeneffect.h>

namespace KWin
{
class GLShader;
}

namespace Kuura
{

/**
 * Frost: the desktop shell's glass "material" effect (Vaihe 4 of the working
 * brief). Renders four visually distinct phenomena on the shell's own
 * translucent surfaces (panels, popups, KRunner) that must NOT be collapsed
 * into a single blur:
 *
 *   1. Background blur (dual-Kawase) -- reused/adapted from KWin's own
 *      built-in Blur effect (src/plugins/blur/ at the pinned KWin tag), not
 *      reimplemented from scratch, per the working brief's own instruction.
 *   2. Edge refraction -- a per-pixel UV offset of the sampled background,
 *      directed along the local edge normal, whose strength decays to zero
 *      over material.refraction.edge_falloff pixels from the edge.
 *   3. Specular edge highlight -- a thin (material.edge_highlight.width
 *      pixel), low-opacity (material.edge_highlight.opacity) bright line
 *      along whichever edge faces a fixed light direction (top-left, per the
 *      brief), simulating a highlight catching the "glass" edge.
 *   4. Subtle dither noise (material.noise) to prevent banding in the
 *      blurred/refracted gradient -- KWin's own blur/shaders/noise.frag
 *      (red-channel-only additive noise, alpha 0) already implements almost
 *      exactly this and is the direct reference.
 *
 * THIS HEADER IS THE LOCKED INTERFACE for the class shape and the CONTRACT
 * each method must satisfy; src/frost.cpp's current body is a placeholder
 * (declared but not yet implementing the shader math), not the finished
 * effect. The real GLSL fragment/vertex shaders this class loads (see
 * LoadShaders() below) are a separate, not-yet-written deliverable.
 *
 * WHY this derives from KWin::OffscreenEffect and NOT from KWin's own
 * BlurEffect (a plausible-sounding but WRONG assumption, corrected by the V4
 * investigation): BlurEffect (src/plugins/blur/blur.h at the pinned tag)
 * derives from plain KWin::Effect and blurs the desktop strictly BEHIND a
 * window via a BackgroundEffectItem scene item -- it never redirects or
 * deforms the window's own texture, because plain background blur does not
 * need to. Frost DOES need to deform the window's own rendered content
 * (the refraction offset, the specular highlight overlay) in addition to
 * showing a blurred background, and OffscreenEffect::apply() is the real,
 * confirmed hook KWin exposes for exactly that (per-window texture
 * redirection + deformation before compositing) -- confirmed by reading
 * offscreeneffect.h at the pinned KWin tag (v6.7.5, commit
 * ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7), not recalled from memory of an
 * older or different KWin version's API, since this API has changed across
 * KWin versions historically.
 *
 * WHICH surfaces Frost applies to: REUSES the exact mechanism KWin's own
 * Blur effect already uses to answer the same question -- confirmed by
 * reading blur.cpp at the pinned tag, not guessed. A window requests
 * background-blur treatment via, in order of surface type: a Wayland
 * surface's own `SurfaceInterface::blurRegion()` (set through the compositor
 * protocol Plasma's shell already uses for every blurred panel/popup/
 * KRunner popup today -- this is the SAME region already driving the plain
 * blur those surfaces get out of the box), an X11 window property
 * (`_KDE_NET_WM_BLUR_BEHIND_REGION`), an internal Qt window's own
 * "kwin_blur" dynamic property, or the active decoration's
 * `decorationBlurRegion()`. Blur detects this in `slotWindowAdded()` (a
 * slot connected to `EffectsHandler::windowAdded`), calling
 * `updateBlurRegion(EffectWindow*)`, and re-detects it at runtime via
 * `SurfaceInterface::blurChanged`, a `QEvent::DynamicPropertyChange` filter
 * for "kwin_blur", and `KDecoration3::Decoration::blurRegionChanged`. Frost
 * follows the identical pattern: a non-empty blur region for a window is
 * exactly the "this window wants the glass material" signal, both at
 * creation and if it changes later -- there is no separate, Frost-specific
 * hint to invent.
 *
 * STILL OPEN, needs a live guest-image test before the blur shader itself is
 * written (do not assume either answer): KWin's effect chain is ordered
 * (`Effect::requestedEffectChainPosition()`, 0-100, low = earlier) and
 * effects call the next one in the chain from within their own paint method
 * -- confirmed from effect.h's own documentation. What is NOT confirmed by
 * that documentation is whether Blur's own BackgroundEffectItem-based
 * rendering (a scene item, not an OffscreenEffect redirect) ends up already
 * present in the texture OffscreenEffect::redirect() captures for the SAME
 * window, if Frost's chain position runs after Blur's. If it does, Frost's
 * own shader only needs to add refraction/specular/noise on top of an
 * already-blurred background (a materially smaller shader than
 * reimplementing dual-Kawase) and can rely on the stock Blur effect staying
 * enabled underneath it; if it does not, Frost needs its own blur pass
 * adapted from blur/shaders/{downsample,upsample}.frag as the class
 * docstring above already anticipated. Resolve this empirically (a minimal
 * build that tints or logs what it actually receives, screenshotted via
 * harness/spike/boot_capture.sh against a real blurred panel) before
 * committing to either shader design.
 */
class Frost : public KWin::OffscreenEffect
{
    Q_OBJECT

public:
    explicit Frost();
    ~Frost() override;

    /**
     * Whether this effect can run at all on the current platform (a real GL
     * context with the shader/FBO features OffscreenEffect needs). Mirrors
     * OffscreenEffect::supported()'s own contract -- Frost must return false
     * here rather than let a later GL call fail, so KWin falls back to
     * plain, un-deformed translucency for the affected surfaces instead of
     * crashing (the working brief's own "no-GPU fallback" requirement).
     */
    static bool supported();

protected:
    /**
     * Deforms one window's already-redirected offscreen texture: applies the
     * edge-refraction UV offset and draws the specular edge highlight, using
     * the shader bound via setShader() in the constructor. Must leave `data`
     * and `quads` consistent with OffscreenEffect's own expectations (see
     * offscreeneffect.h's own documentation of this hook) -- does not itself
     * decide WHETHER a window should be affected; that filtering happens
     * before redirect() is ever called for a given window (see the class
     * docstring's open question about surface selection).
     *
     * @param window the window being composited this frame
     * @param mask compositing paint mask, forwarded from KWin, not
     *     interpreted by this method beyond passing it through
     * @param data paint data (opacity, transform, ...) this method may
     *     adjust before the base class composites the deformed texture
     * @param quads the window's paint quads; unmodified unless the
     *     refraction offset needs to be expressed as a geometry change
     *     rather than a pure fragment-shader UV offset (to be determined
     *     empirically against the real API, not assumed here)
     */
    void apply(KWin::EffectWindow *window, int mask, KWin::WindowPaintData &data, KWin::WindowQuadList &quads) override;

private:
    /**
     * Decides whether one window currently wants the glass material, by the
     * same rule KWin's own Blur effect uses (see the class docstring): a
     * non-empty blur region from any of its sources (Wayland surface, X11
     * property, internal Qt property, decoration). Calls redirect(window) if
     * so and the window is not already redirected, or unredirect(window) if
     * a previously-qualifying window no longer has one -- mirrors
     * BlurEffect::updateBlurRegion()'s role, not its exact implementation
     * (Frost does not store the region's geometry itself; only whether one
     * exists governs whether this window is redirected at all).
     *
     * @param window the window whose blur-region state to (re-)check
     */
    void updateWindowState(KWin::EffectWindow *window);

    /**
     * Connected to EffectsHandler::windowAdded (constructor) to call
     * updateWindowState() for every new window, mirroring
     * BlurEffect::slotWindowAdded()'s role. A window's INITIAL blur-region
     * state is only known once it is mapped, not from window-addition alone
     * -- verify live (see the class docstring's still-open question) exactly
     * which additional per-window signal(s) (Wayland surface blurChanged,
     * the internal-window dynamic-property filter, or the decoration's
     * blurRegionChanged) this constructor must also connect, matching
     * BlurEffect's own set, so a window that requests blur AFTER being added
     * is not missed.
     *
     * @param window the newly added window
     */
    void slotWindowAdded(KWin::EffectWindow *window);


    /**
     * Compiles/links the fragment+vertex shader pair via
     * KWin::ShaderManager::instance()->loadShaderFromCode(...) and stores the
     * result for apply() to bind with setShader(). Not yet given real shader
     * source (see the class docstring) -- the current placeholder body must
     * not silently "succeed" with an empty/no-op shader; it should leave the
     * effect in the same safe, disabled state supported() = false would
     * produce, until real shaders exist.
     */
    void loadShaders();

    KWin::GLShader *m_shader = nullptr;
};

} // namespace Kuura
