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
 * WHICH surfaces Frost applies to (Plasma's own panels/popups/KRunner, not
 * arbitrary application windows) is NOT YET DECIDED IN CODE -- the real
 * mechanism KWin uses to know a surface wants background-blur treatment at
 * all (the blur-behind region hint, X11 property / Wayland protocol) needs
 * its own live investigation before Frost::apply() can correctly decide
 * which windows to touch; this header intentionally does not guess that
 * surface-selection logic yet. See the project's own memory / V4 investigation
 * notes for the current state of that open question.
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
