#include "frost.h"

// Confirmed live at /usr/include/kwin/opengl/glshadermanager.h and
// /usr/include/kwin/opengl/glshader.h against the pinned Arch snapshot's kwin
// package (V4 investigation notes).
#include <opengl/glshader.h>
#include <opengl/glshadermanager.h>
#include <effect/effecthandler.h>

namespace Kuura
{

Frost::Frost()
{
    // WHY connect here, not rely on a base-class default: OffscreenEffect
    // does not itself decide which windows to redirect -- that is this
    // effect's own responsibility, following BlurEffect::slotWindowAdded()'s
    // precedent exactly (see frost.h's class docstring). `effects` is
    // KWin's real global EffectsHandler pointer, used the same way
    // throughout its own effect plugins, including blur.cpp.
    connect(KWin::effects, &KWin::EffectsHandler::windowAdded, this, &Frost::slotWindowAdded);
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

void Frost::loadShaders()
{
    // PLACEHOLDER: no real shader source exists yet (see frost.h's class
    // docstring). Deliberately leaves m_shader null rather than loading a
    // no-op/empty shader that would silently "succeed" -- apply() below
    // checks for this and does nothing until real shaders are written, the
    // same safe-disabled behaviour supported() = false would produce.
}

void Frost::slotWindowAdded(KWin::EffectWindow *window)
{
    updateWindowState(window);
    // PLACEHOLDER: does not yet connect the window's own later-blur-region-
    // change signals (Wayland surface blurChanged, internal-window dynamic-
    // property filter, decoration blurRegionChanged) -- see frost.h's class
    // docstring for why this still needs live verification before it can be
    // done correctly rather than guessed.
}

void Frost::updateWindowState(KWin::EffectWindow *window)
{
    // PLACEHOLDER: does not yet read the window's actual blur region from any
    // of its real sources (see frost.h's class docstring) or call
    // redirect()/unredirect() -- so no window is ever redirected yet, the
    // same safe-disabled behaviour as loadShaders() until this is written for
    // real.
    Q_UNUSED(window)
}

void Frost::apply(KWin::EffectWindow *window, int mask, KWin::WindowPaintData &data, KWin::WindowQuadList &quads)
{
    if (!m_shader) {
        return;
    }
    // PLACEHOLDER: refraction/specular-highlight shader binding and uniform
    // upload is not yet implemented (see frost.h's class docstring for the
    // real, confirmed apply() contract this must satisfy).
    Q_UNUSED(window)
    Q_UNUSED(mask)
    Q_UNUSED(data)
    Q_UNUSED(quads)
}

} // namespace Kuura
