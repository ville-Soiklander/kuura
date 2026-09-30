#pragma once

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
 *   - `refractionStrength`, `refractionEdgeFalloff`, `edgeHighlightWidth`,
 *     `edgeHighlightOpacity`, `noiseAmount`
 *                     The five material.* design tokens frost.h's apply()
 *                     docstring lists (material.refraction.strength/
 *                     edge_falloff, material.edge_highlight.width/opacity,
 *                     material.noise). Their VALUES never appear as literals in
 *                     this shader source -- see frost.cpp's own citation for
 *                     where the real numbers (design/tokens.json, via the
 *                     generated design/generators/cpp_header.py header) are
 *                     uploaded from, and why that happens once at shader-link
 *                     time rather than every frame in apply().
 *
 * The four numbered comment blocks in the shader body below correspond exactly
 * to points 1-4 of frost.h's apply() docstring (edge distance, refraction,
 * specular highlight, dither noise) -- read that docstring alongside this file
 * for the worked-through derivation each formula comes from.
 */
inline constexpr const char *kFrostFragmentShaderSource = R"GLSL(#version 140
uniform sampler2D sampler;
uniform vec4 modulation;
uniform int textureWidth;
uniform int textureHeight;
uniform sampler2D noiseSampler;
uniform vec2 noiseTextureSize;
uniform float refractionStrength;
uniform float refractionEdgeFalloff;
uniform float edgeHighlightWidth;
uniform float edgeHighlightOpacity;
uniform float noiseAmount;
in vec2 texcoord0;
out vec4 fragColor;

void main(void)
{
    vec2 windowSize = vec2(float(textureWidth), float(textureHeight));
    vec2 pixelPos = texcoord0 * windowSize;

    // ---- 1. EDGE DISTANCE (apply() docstring, point 1) ----
    // Distance in pixels to each of the four edges; the nearest one's distance
    // is edgeDist, and its outward-facing unit normal drives the refraction
    // offset direction below.
    float distLeft = pixelPos.x;
    float distRight = windowSize.x - pixelPos.x;
    float distTop = pixelPos.y;
    float distBottom = windowSize.y - pixelPos.y;
    float edgeDist = min(min(distLeft, distRight), min(distTop, distBottom));

    // WHY a plain if/else chain instead of a branchless "index of the minimum"
    // trick: edgeDist was already computed as the min of the four distances
    // above, so re-comparing against it here is just recovering WHICH of those
    // four distances it came from, in the exact left/right/top/bottom order the
    // docstring itself enumerates. A tie (an exact corner pixel) picks whichever
    // branch is checked first; this only affects the refraction offset's
    // direction at a single-pixel corner case, never the highlight (point 3
    // uses pixelPos directly, not this normal) or the falloff magnitude.
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

    // ---- 2. EDGE REFRACTION (apply() docstring, point 2) ----
    // falloff is exactly 1.0 at the edge itself, linearly reaching 0.0 at
    // refractionEdgeFalloff pixels inward. max() with a tiny epsilon guards the
    // division only against a pathological edge_falloff of exactly 0 (a
    // degenerate token value outside today's real tokens.json, not a case the
    // docstring's own formula needs to handle, but dividing by a real, non-zero
    // token value is unaffected by it).
    float falloff = clamp(1.0 - edgeDist / max(refractionEdgeFalloff, 0.0001), 0.0, 1.0);
    // strength reads as a FRACTION of the falloff distance (docstring's own
    // worked example: strength=0.035, edge_falloff=12px -> ~0.42px maximum
    // displacement right at the edge), hence the product below rather than
    // strength alone.
    vec2 offsetPixels = normal * (refractionStrength * refractionEdgeFalloff) * falloff;
    // Convert the pixel offset to UV and clamp: sampling past the texture edge
    // is undefined/wraps, not "no refraction" (docstring's own explicit call-out).
    vec2 refractedUv = clamp(texcoord0 + offsetPixels / windowSize, 0.0, 1.0);
    vec4 refracted = texture(sampler, refractedUv);

    // ---- 3. SPECULAR EDGE HIGHLIGHT (apply() docstring, point 3) ----
    // Fixed top-left light direction: only the top and left edges ever
    // contribute. max(), NOT addition, so a pixel near the top-left CORNER
    // (on both edges' falloff ranges at once) is not double-brightened.
    float topStrength = clamp(1.0 - pixelPos.y / edgeHighlightWidth, 0.0, 1.0);
    float leftStrength = clamp(1.0 - pixelPos.x / edgeHighlightWidth, 0.0, 1.0);
    float highlight = max(topStrength, leftStrength);
    vec3 highlighted = mix(refracted.rgb, vec3(1.0), highlight * edgeHighlightOpacity);

    // ---- 4. DITHER NOISE (apply() docstring, point 4) ----
    // Same tiled-noise-texture/gl_FragCoord sampling convention KWin's own
    // blur/shaders/noise.frag uses (fetched and confirmed live, see this file's
    // own header comment) -- adapted from that shader's SEPARATE additive blend
    // PASS into a single inline addition here, because OffscreenData::paint()
    // (the base class Frost cannot override) only issues ONE draw call with
    // Frost's one bound shader; there is no second pass available to blend a
    // noise-only draw onto, unlike Blur's own two-pass architecture.
    float noiseSample = texture(noiseSampler, gl_FragCoord.xy / noiseTextureSize).r;
    vec3 withNoise = highlighted + vec3(noiseSample * noiseAmount);

    fragColor = vec4(withNoise, refracted.a) * modulation;
}
)GLSL";

/**
 * Minimal vertex shader used ONLY by the offscreen correctness test rig
 * (tests/offscreen_shader_test.cpp), which links no KWin/ShaderManager at all
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
