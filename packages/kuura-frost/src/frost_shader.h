#pragma once

// Generated from design/tokens.json at package-build time (material.edge_highlight.light_*).
#include <tokens.h>

// The real material fragment shader source (Vaihe 4's locked mathematical
// specification -- see frost.h's apply() docstring, points 1-4, which this file
// implements verbatim) as ONE shared string, included by BOTH the real KWin
// plugin (frost.cpp's loadShaders()) and the standalone offscreen
// shader-correctness test rig (tests/offscreen_shader_test.cpp). Sharing the
// literal source, rather than each side keeping its own copy, is what the
// working brief's own test-rig requirement asks for explicitly ("do not
// duplicate the GLSL as a second, drifting copy") -- a change to the math here
// is a change to what BOTH the plugin and its own correctness test compile.
//
// Plain `const char *`, not a Qt type: the test rig links no Qt at all (it only
// needs EGL/GL), and frost.cpp already has to wrap this in a QByteArray itself
// wherever KWin's own API expects one (ShaderManager::generateCustomShader()'s
// signature), so nothing is lost by keeping the shared constant Qt-free.

namespace Kuura
{

/**
 * The real glass "material" fragment shader.
 *
 * Traits: MapTexture (samples Frost's own captured/redirected texture) and
 * Modulate (OffscreenData::paint() unconditionally writes a `modulation`
 * uniform regardless of which shader is bound -- confirmed at
 * opengl/offscreeneffect.cpp's own paint(), same citation the former
 * diagnostic-only version of this shader already used). No other trait is
 * requested: AdjustSaturation/TransformColorspace remain unused for the same
 * reason the former diagnostic shader's own comment gave (they pull in
 * saturation.glsl/colormanagement.glsl complexity this shader does not need),
 * and that reasoning is unaffected by replacing the tint with the real material
 * math below.
 *
 * `#version 140` is first because KWin::ShaderManager::generateCustomShader()
 * (opengl/glshadermanager.cpp, fetched and read at the pinned tag, v6.7.5,
 * commit ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7) does plain string
 * concatenation, `defines + fragmentSource` (its own listDefines() output,
 * `#define TRAIT_...` lines, PREPENDED ahead of whatever source is given) --
 * confirmed by reading generateCustomShader() itself, not assumed from the
 * former diagnostic shader's comment alone. KWin's own base.frag (same fetch)
 * uses the identical "#version first, TRAIT_ defines land before it" layout, so
 * this is the project's real, already-shipping convention, not a guess.
 *
 * Uniform names and where each real one comes from (every single one verified
 * live against the pinned tag, not assumed -- see frost.cpp's own citations for
 * the fetch commands):
 *   - `sampler`      MapTexture trait's own real sampler name (matches the
 *                     former diagnostic shader; texture unit 0 is GLSL's own
 *                     default for an unspecified sampler, and nothing in this
 *                     pipeline ever moves Frost's OWN captured texture off
 *                     unit 0 -- see frost.cpp's own citation on why the noise
 *                     sampler below uses unit 1 instead).
 *   - `modulation`    Modulate trait; OffscreenData::paint() sets this every
 *                     frame regardless of which shader is bound.
 *   - `textureWidth`, `textureHeight`
 *                     REAL per-frame pixel dimensions of Frost's own captured
 *                     texture, in DEVICE pixels (already scaled for the
 *                     output's scale factor) -- set EVERY FRAME by the base
 *                     class itself, unconditionally, via
 *                     `shader->setUniform(GLShader::IntUniform::TextureWidth,
 *                     m_texture->width())` / `...TextureHeight...`
 *                     (opengl/offscreeneffect.cpp's own OffscreenData::paint()),
 *                     whose real uniform NAMES are "textureWidth"/"textureHeight"
 *                     (confirmed at opengl/glshader.cpp's own resolveLocations():
 *                     `m_intLocations[IntUniform::TextureWidth] =
 *                     uniformLocation("textureWidth");`). This is frost.h's own
 *                     apply() docstring's "windowSize" quantity -- see frost.cpp's
 *                     own citation for why NEITHER apply() NOR loadShaders() sets
 *                     it explicitly: the base class already does, every frame,
 *                     for any OffscreenEffect subclass's bound shader, and doing
 *                     so from a logical EffectWindow::width()/height() accessor
 *                     instead (also real, effect/effectwindow.h, but LOGICAL,
 *                     unscaled coordinates) would be WRONG at any output scale
 *                     other than 1.0, since this per-pixel math must match the
 *                     texture's own real pixel grid, not logical window size.
 *   - `glassRect`     (x, y, width, height) of the window's blur-region
 *                     bounding box, in device pixels with a TOP-LEFT origin,
 *                     relative to Frost's captured texture (which spans the
 *                     window's expanded geometry, shadow included). Set PER
 *                     WINDOW, PER FRAME by Frost::apply() (bind/set/unbind via
 *                     ShaderManager::pushShader()/popShader()). Edge distance,
 *                     highlight, light-surface hairline and noise all apply inside
 *                     this rect; everything outside it is passed through
 *                     unchanged. A zero-size rect (the GLSL default before the
 *                     first upload) disables the material entirely.
 *   - `noiseSampler`, `noiseTextureSize`
 *                     Frost's OWN tiled grayscale noise texture (see frost.cpp's
 *                     m_noiseTexture) and its real pixel size, bound to texture
 *                     unit 1 by apply() every frame -- NOT a shared object with
 *                     KWin's own Blur effect (confirmed impossible: Blur's own
 *                     noise texture, `BlurEffect::m_noisePass.noiseTexture`, is a
 *                     private, non-exposed std::unique_ptr<GLTexture> member of
 *                     the BlurEffect instance itself -- plugins/blur/blur.cpp's
 *                     own ensureNoiseTexture(), fetched and read in full). The
 *                     SAMPLING CONVENTION (gl_FragCoord.xy / noiseTextureSize,
 *                     a tiled GL_REPEAT texture) is reused verbatim from KWin's
 *                     own real, shipping plugins/blur/shaders/noise.frag
 *                     (fetched at the pinned tag) -- proof that `gl_FragCoord`
 *                     is usable inside a ShaderManager trait-generated custom
 *                     shader exactly like this one, since noise.frag is loaded
 *                     the same way (`ShaderManager::generateShaderFromFile(
 *                     ShaderTrait::MapTexture, ...)`, blur.cpp) as this shader is
 *                     (`generateCustomShader(ShaderTrait::MapTexture |
 *                     ShaderTrait::Modulate, ...)`, frost.cpp).
 *   - `edgeHighlightWidth`, `edgeHighlightOpacity`, `noiseAmount`
 *                     material.edge_highlight.width/opacity and material.noise
 *                     (design/tokens.json via the generated <tokens.h>), uploaded
 *                     once at link time by frost.cpp's loadShaders(). Their
 *                     VALUES never appear as literals in this shader source.
 *   - `lightRimOpacity`, `lightRimWidth`, `lightRimLumaLow`, `lightRimLumaHigh`
 *                     The light-surface rim (see "LIGHT-SURFACE RIM" below and
 *                     the material.edge_highlight.light_* tokens). Uploaded once at link time like the
 *                     tokens above.
 *
 * WHAT THIS SHADER NO LONGER DOES (requirement change 2026-10-20): it does not
 * refract. Edge refraction is a property of the BACKDROP seen through the
 * glass, and Frost's captured texture never contains the backdrop (frost.h,
 * requestedEffectChainPosition()). Refraction is now done on the real render
 * target by kFrostBackdropFragmentShaderSource below, drawn by
 * Frost::drawWindow() before the window is composited. Displacing the window's
 * own content (the former behaviour) shifted text and icons near the edge,
 * which is not what the design describes.
 *
 * LIGHT-SURFACE RIM (requirement change 2026-10-20): the white top/left
 * highlight mixes toward premultiplied white, so its visible contribution is
 * proportional to the surface's remaining headroom (alpha - rgb). On a
 * near-white light-scheme surface that headroom is almost zero and the rim
 * vanished. The shader therefore measures the window pixel's own
 * (un-premultiplied) luminance and, on light surfaces only, (a) darkens a thin
 * outer hairline of `lightRimWidth` device pixels along all four glass edges
 * by `lightRimOpacity`, and (b) moves the white highlight inward by the same
 * width so it sits just inside the hairline instead of being cancelled by it.
 * The light weight is smoothstep(lightRimLumaLow, lightRimLumaHigh, luma), so a
 * dark-scheme surface (luma far below lightRimLumaLow) gets weight exactly 0
 * and renders exactly as before.
 *
 * The numbered comment blocks in the shader body correspond to frost.h's
 * apply() docstring (edge distance, specular highlight, dither noise).
 */
inline constexpr const char *kFrostFragmentShaderSource = R"GLSL(#version 140
uniform sampler2D sampler;
uniform vec4 modulation;
uniform int textureWidth;
uniform int textureHeight;
uniform vec4 glassRect;
uniform sampler2D noiseSampler;
uniform vec2 noiseTextureSize;
uniform float edgeHighlightWidth;
uniform float edgeHighlightOpacity;
uniform float noiseAmount;
uniform float lightRimOpacity;
uniform float lightRimWidth;
uniform float lightRimLumaLow;
uniform float lightRimLumaHigh;
in vec2 texcoord0;
out vec4 fragColor;

void main(void)
{
    vec2 windowSize = vec2(float(textureWidth), float(textureHeight));

    // ---- 0. COORDINATE FRAME + GLASS RECT ----
    // texcoord0 is GL's bottom-up texture space: OffscreenData::paint() runs the
    // quad's top-left (0,0) texcoord through GLTexture::matrix(), which flips v
    // for an FBO-allocated texture (v' = 1 - v), and the capture itself is
    // rendered with the window's TOP at the texture's high-v rows. Converting to
    // a top-left-origin pixel position here is what makes "top"/"left" below
    // mean the window's real top/left edge on screen.
    vec2 pixelPos = vec2(texcoord0.x, 1.0 - texcoord0.y) * windowSize;
    vec4 base = texture(sampler, texcoord0);

    // glassRect (x, y, width, height; device pixels, top-left origin, relative
    // to this texture) is the bounding box of the window's blur region. The
    // texture spans the window's whole EXPANDED geometry (shadow included), so
    // measuring edges from the texture border would put the rim on the outer
    // edge of the shadow. Outside the rect (or before Frost has uploaded one),
    // the window is passed through untouched.
    vec2 local = pixelPos - glassRect.xy;
    if (glassRect.z <= 0.0 || glassRect.w <= 0.0 || local.x < 0.0 || local.y < 0.0
        || local.x > glassRect.z || local.y > glassRect.w) {
        fragColor = base * modulation;
        return;
    }

    // ---- 1. LIGHT WEIGHT ----
    // Un-premultiply before measuring: a half-transparent white texel is
    // (0.5, 0.5, 0.5, 0.5) premultiplied, and its colour is white, not grey.
    // Rec. 709 luma weights on the stored (sRGB-encoded) values: this is a
    // "is the surface light" classifier, not a colorimetric measurement, so the
    // encoding does not matter as long as the thresholds use the same one.
    float luma = dot(base.rgb / max(base.a, 0.0001), vec3(0.2126, 0.7152, 0.0722));
    float lightWeight = smoothstep(lightRimLumaLow, lightRimLumaHigh, luma);

    // ---- 2. SPECULAR EDGE HIGHLIGHT (apply() docstring, point 3) ----
    // Fixed top-left light direction: only the glass rect's top and left edges
    // contribute. max(), NOT addition, so a pixel near the top-left CORNER is
    // not double-brightened. On light surfaces the highlight starts `shift`
    // pixels inside the edge (just inside the dark hairline, step 3); the
    // step() keeps it off the hairline itself. With lightWeight == 0, shift is
    // 0 and step() is always 1 inside the rect: the dark-scheme formula is the
    // unchanged original.
    float shift = lightWeight * lightRimWidth;
    float topD = local.y - shift;
    float leftD = local.x - shift;
    float topStrength = clamp(1.0 - topD / edgeHighlightWidth, 0.0, 1.0) * step(0.0, topD);
    float leftStrength = clamp(1.0 - leftD / edgeHighlightWidth, 0.0, 1.0) * step(0.0, leftD);
    float highlight = max(topStrength, leftStrength);
    // WHY mix toward vec3(alpha) and not vec3(1.0): the captured texture is
    // PREMULTIPLIED (OffscreenData::paint() blends with GL_ONE,
    // GL_ONE_MINUS_SRC_ALPHA), so "white at this pixel's coverage" is
    // (a, a, a). Mixing toward pure 1.0 would emit light where the window is
    // transparent (a rounded corner inside the bounding rect).
    vec3 highlighted = mix(base.rgb, vec3(base.a), highlight * edgeHighlightOpacity);

    // ---- 3. LIGHT-SURFACE HAIRLINE ----
    // Pixel coverage of the band [0, lightRimWidth] from each of the four
    // edges (a pixel centre at distance d covers the band by lightRimWidth - d
    // + 0.5, clamped), so a fractional width antialiases instead of snapping.
    // Darkening scales premultiplied rgb only: rgb stays <= alpha and a fully
    // transparent texel stays fully transparent (no line drawn where there is
    // no glass).
    float edgeDist = min(min(local.x, glassRect.z - local.x), min(local.y, glassRect.w - local.y));
    float hairline = clamp(lightRimWidth - edgeDist + 0.5, 0.0, 1.0) * lightWeight;
    vec3 rimmed = highlighted * (1.0 - hairline * lightRimOpacity);

    // ---- 4. DITHER NOISE (apply() docstring, point 4) ----
    // Same tiled-noise-texture/gl_FragCoord sampling convention KWin's own
    // blur/shaders/noise.frag uses, applied inline because OffscreenData::paint()
    // issues exactly one draw with this shader. Scaled by alpha for the same
    // premultiplied-coverage reason as the highlight above.
    float noiseSample = texture(noiseSampler, gl_FragCoord.xy / noiseTextureSize).r;
    vec3 withNoise = rimmed + vec3(noiseSample * noiseAmount * base.a);

    fragColor = vec4(withNoise, base.a) * modulation;
}
)GLSL";

/**
 * Backdrop edge-refraction fragment shader, drawn by Frost::drawWindow() onto
 * the REAL render target, after KWin's Blur has drawn the frosted backdrop and
 * before Frost composites the window over it (frost.h, drawWindow()).
 *
 * Input `sampler` is Frost's per-window copy of that frosted backdrop: a
 * texture exactly covering the glass bounding box in device pixels, filled by
 * GLFramebuffer::blitFromRenderTarget() (opengl/glframebuffer.cpp) the same way
 * BlurEffect::blur() fills its own first framebuffer (plugins/blur/blur.cpp).
 * Texture coordinates follow Blur's on-screen pass convention: u = x / width,
 * v = 1 - y / height for a top-left-origin device position (x, y).
 *
 * Uniforms:
 *   - `backdropSize`  the copy texture's size in device pixels (= glass bbox).
 *   - `refractionStrength`, `refractionEdgeFalloff`
 *                     material.refraction.strength / edge_falloff tokens.
 *
 * Math (frost.h apply() docstring points 1-2, now applied to the backdrop):
 * edgeDist and the outward normal of the NEAREST bbox edge; falloff = clamp(1 -
 * edgeDist / edge_falloff, 0, 1); displacement = strength * edge_falloff *
 * falloff pixels. The sample is taken INWARD (local - normal * displacement):
 * a lens edge pulls the image from further inside, so the backdrop near the
 * rim looks slightly stretched toward the edge. Inward also guarantees every
 * sample lies inside the glass, where Blur's output is: an outward sample
 * would read the sharp, unblurred desktop around the window (and, for a
 * rounded glass shape, an inward axis-aligned step from an inside point stays
 * inside, since a rounded rectangle is orthogonally convex).
 *
 * Output is written with blending DISABLED: it replaces the backdrop pixels
 * in the band with their displaced copy, alpha included. The copy holds the
 * same premultiplied values the target held, and bilinear filtering of
 * premultiplied values is itself premultiplied-correct, so no un/re-
 * premultiplication is needed.
 */
inline constexpr const char *kFrostBackdropFragmentShaderSource = R"GLSL(#version 140
uniform sampler2D sampler;
uniform vec2 backdropSize;
uniform float refractionStrength;
uniform float refractionEdgeFalloff;
in vec2 texcoord0;
out vec4 fragColor;

void main(void)
{
    vec2 local = vec2(texcoord0.x, 1.0 - texcoord0.y) * backdropSize;

    float distLeft = local.x;
    float distRight = backdropSize.x - local.x;
    float distTop = local.y;
    float distBottom = backdropSize.y - local.y;
    float edgeDist = min(min(distLeft, distRight), min(distTop, distBottom));

    // Recover which edge is nearest (ties at an exact corner take the first
    // listed; only the direction of a sub-pixel step at that one pixel differs).
    vec2 normal;
    if (edgeDist == distLeft) {
        normal = vec2(-1.0, 0.0);
    } else if (edgeDist == distRight) {
        normal = vec2(1.0, 0.0);
    } else if (edgeDist == distTop) {
        normal = vec2(0.0, -1.0);
    } else {
        normal = vec2(0.0, 1.0);
    }

    // max() guards the division only against a degenerate edge_falloff of 0.
    float falloff = clamp(1.0 - edgeDist / max(refractionEdgeFalloff, 0.0001), 0.0, 1.0);
    vec2 offsetPixels = normal * (refractionStrength * refractionEdgeFalloff) * falloff;
    // Inward sample; the clamp to texel centres only matters for a glass rect
    // thinner than twice the displacement, and keeps bilinear filtering from
    // reading past the copy.
    vec2 sampleLocal = clamp(local - offsetPixels, vec2(0.5), max(backdropSize - vec2(0.5), vec2(0.5)));
    fragColor = texture(sampler, vec2(sampleLocal.x / backdropSize.x, 1.0 - sampleLocal.y / backdropSize.y));
}
)GLSL";

/**
 * Minimal vertex shader used ONLY by the offscreen correctness test rig
 * (tests/offscreen_shader_test.cpp, for both fragment shaders above), which links no KWin/ShaderManager at all
 * and therefore cannot rely on ShaderManager::generateCustomShader() to
 * auto-generate one the way the real plugin does (frost.cpp's loadShaders()
 * passes an empty vertex source for exactly that reason). This is a hand-written
 * equivalent of the REAL vertex shader ShaderManager would generate for the
 * MapTexture trait -- copied from KWin's own real, fetched
 * src/opengl/base.vert at the pinned tag (its `#if TRAIT_MAP_TEXTURE` branch),
 * not guessed: `in vec4 position`, `in vec4 texcoord`, `out vec2 texcoord0`
 * assigned `texcoord.st` (NOT a vec2 texcoord attribute -- base.vert's real
 * attribute is vec4, only its first two components are used), and
 * `modelViewProjectionMatrix`. This file carries no "material" math at all
 * (see this header's own top comment on why sharing GLSL matters for
 * kFrostFragmentShaderSource specifically, not this trivial passthrough).
 */
inline constexpr const char *kFrostTestVertexShaderSource = R"GLSL(#version 140
in vec4 position;
in vec4 texcoord;
out vec2 texcoord0;
uniform mat4 modelViewProjectionMatrix;

void main(void)
{
    texcoord0 = texcoord.st;
    gl_Position = modelViewProjectionMatrix * position;
}
)GLSL";

} // namespace Kuura
