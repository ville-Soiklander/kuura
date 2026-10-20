// Offscreen correctness test for Frost's real material fragment shader
// (src/frost_shader.h), per frost.h's apply() docstring ("TESTABLE WITHOUT A
// REAL KWIN SESSION"). Standalone: links no KWin/Qt at all, only EGL + desktop
// OpenGL (mesa's own software rasterizer, llvmpipe, at the pinned toolchain) --
// it must not require booting the guest VM or loading into a real KWin session.
//
// WHAT THIS PROVES: it renders a full-screen quad with the SAME fragment
// shader source frost.cpp's own loadShaders() compiles (src/frost_shader.h,
// included by both, never duplicated -- see that header's own top comment for
// why), sampling a small, fully known, procedurally generated input texture,
// then reads back specific pixels and compares them against values HAND-
// COMPUTED from frost.h's apply() docstring formulas (points 1-3: edge
// distance, refraction, specular highlight) -- the arithmetic is worked out in
// the comments below, not derived by running the shader once and copying its
// output (that would prove nothing). Passes 6-7 cover the light-surface rim
// (frost_shader.h, "LIGHT-SURFACE RIM") and pass 8 the backdrop refraction
// shader (kFrostBackdropFragmentShaderSource) -- both added 2026-10-20, when
// refraction moved from the window's own content to the backdrop. Point 4 (dither noise) is inherently
// random by design and cannot have a single "hand-computed" expected value;
// it is instead checked for the correct BOUNDED, non-negative, additive
// contribution its own formula promises (see expectNoiseBounded in main()).
//
// TEST GEOMETRY (chosen once, reused by every check below):
//   - windowSize (the shader's own textureWidth/textureHeight uniforms) =
//     100 x 50 "pixels". The output framebuffer is rendered at exactly this
//     100x50 resolution, so pixel (px, py) [0-indexed, glReadPixels convention,
//     row 0 = BOTTOM] has a fragment-shader texcoord0 of exactly
//     ((px+0.5)/100, (py+0.5)/50).
//   - The shader converts texcoord0 to a TOP-LEFT-origin pixel position,
//     pixelPos = (u * 100, (1 - v) * 50), because KWin hands it GL's bottom-up
//     v axis (GLTexture::matrix() flips v for the FBO-allocated capture
//     texture, and the capture renders the window's top at high v). So
//     readPixel(px, py) shows pixelPos = (px + 0.5, 50 - (py + 0.5)): the
//     window's TOP edge is glReadPixels row 49, its BOTTOM edge is row 0. The
//     TOP EDGE / BOTTOM EDGE checks below pin this orientation down; an
//     earlier version of the shader had it upside down (highlight on the
//     bottom edge), which no check caught because none looked at it.
//   - glassRect (the shader's per-window blur-region bounding box, top-left
//     origin, device pixels) is (0, 0, 100, 50) -- the whole texture -- for
//     passes 1-2, a strict sub-rect for pass 3, all-zero for pass 4.
//   - The input "captured background" texture is a 512x512 RGBA8 gradient,
//     GL_LINEAR filtered, GL_CLAMP_TO_EDGE wrapped, where texel (tx, ty) [any
//     of the 512x512 grid] stores R = round(u_center*255), G =
//     round(v_center*255), B = 128 (constant, unused by the math, just a
//     sanity marker), A = 255, with u_center = (tx+0.5)/512, v_center =
//     (ty+0.5)/512 -- i.e. the texel's own centre UV coordinate, scaled to a
//     byte. Bilinearly sampling a texture that stores "its own centre UV" at
//     every texel reproduces the QUERIED continuous UV almost exactly (linear
//     interpolation of an (8-bit-quantized) linear function is itself linear),
//     so `sampled.r/255 ~= queried_u`, `sampled.g/255 ~= queried_v` for any
//     query reasonably far from the [0,1] edges. This is what makes reading
//     the refracted colour back tell us exactly which UV the shader actually
//     sampled -- a solid-colour texture (the other example the working brief
//     suggests) cannot do this, since any refraction offset into a solid
//     colour still reads back as that same solid colour.
//   - Error budget for every "hand-computed" comparison below: EPSILON_BYTES
//     = 3 (out of 255), covering (a) the input texture's own 8-bit
//     quantization of each texel's stored centre-UV value (+/-0.5), (b)
//     bilinear blending between two independently-quantized texels (bounded
//     by the same +/-0.5), (c) the output framebuffer's own 8-bit
//     quantization on glReadPixels (+/-0.5), and (d) GL_CLAMP_TO_EDGE
//     saturating a query within about one texel-width of a texture edge to
//     that edge texel's own (already-quantized) value rather than
//     extrapolating past it -- a real effect only for the CORNER check below
//     (pixelPos very close to 0), shown by direct calculation in that check's
//     own comment to still land inside this same budget.

#include "../src/frost_shader.h"
#include <tokens.h>

#include <EGL/egl.h>
#include <GL/gl.h>
// gl.h alone does not reliably declare every core token this file needs
// (GL_CLAMP_TO_EDGE is GL 1.2, GL_RED as an internal/pixel format is GL 3.0) --
// glext.h is the standard, always-present companion header that fills these
// in (guarded per GL-version block, so it does not conflict with anything
// gl.h already defined).
#include <GL/glext.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <tuple>
#include <utility>
#include <vector>

namespace
{

// ---------------------------------------------------------------------------
// Minimal GL function loading. This test rig links only libEGL/libGL (no
// GLEW/glad/epoxy -- see this project's own PKGBUILD license-check discipline
// in CLAUDE.md: this avoids needing to vet a new third-party dependency at
// all). glGetProcAddress() is the portable, spec-correct way to obtain any GL
// entry point beyond the fixed GL 1.1 core that <GL/gl.h> itself declares.
// ---------------------------------------------------------------------------

using PFNGLGENBUFFERSPROC = void (*)(GLsizei, GLuint *);
using PFNGLBINDBUFFERPROC = void (*)(GLenum, GLuint);
using PFNGLBUFFERDATAPROC = void (*)(GLenum, ptrdiff_t, const void *, GLenum);
using PFNGLGENVERTEXARRAYSPROC = void (*)(GLsizei, GLuint *);
using PFNGLBINDVERTEXARRAYPROC = void (*)(GLuint);
using PFNGLENABLEVERTEXATTRIBARRAYPROC = void (*)(GLuint);
using PFNGLVERTEXATTRIBPOINTERPROC = void (*)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
using PFNGLCREATESHADERPROC = GLuint (*)(GLenum);
using PFNGLSHADERSOURCEPROC = void (*)(GLuint, GLsizei, const char *const *, const GLint *);
using PFNGLCOMPILESHADERPROC = void (*)(GLuint);
using PFNGLGETSHADERIVPROC = void (*)(GLuint, GLenum, GLint *);
using PFNGLGETSHADERINFOLOGPROC = void (*)(GLuint, GLsizei, GLsizei *, char *);
using PFNGLCREATEPROGRAMPROC = GLuint (*)();
using PFNGLATTACHSHADERPROC = void (*)(GLuint, GLuint);
using PFNGLBINDATTRIBLOCATIONPROC = void (*)(GLuint, GLuint, const char *);
using PFNGLLINKPROGRAMPROC = void (*)(GLuint);
using PFNGLGETPROGRAMIVPROC = void (*)(GLuint, GLenum, GLint *);
using PFNGLGETPROGRAMINFOLOGPROC = void (*)(GLuint, GLsizei, GLsizei *, char *);
using PFNGLUSEPROGRAMPROC = void (*)(GLuint);
using PFNGLGETUNIFORMLOCATIONPROC = GLint (*)(GLuint, const char *);
using PFNGLUNIFORM1IPROC = void (*)(GLint, GLint);
using PFNGLUNIFORM1FPROC = void (*)(GLint, GLfloat);
using PFNGLUNIFORM2FPROC = void (*)(GLint, GLfloat, GLfloat);
using PFNGLUNIFORM4FPROC = void (*)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
using PFNGLUNIFORMMATRIX4FVPROC = void (*)(GLint, GLsizei, GLboolean, const GLfloat *);
using PFNGLACTIVETEXTUREPROC = void (*)(GLenum);
using PFNGLGENFRAMEBUFFERSPROC = void (*)(GLsizei, GLuint *);
using PFNGLBINDFRAMEBUFFERPROC = void (*)(GLenum, GLuint);
using PFNGLFRAMEBUFFERTEXTURE2DPROC = void (*)(GLenum, GLenum, GLenum, GLuint, GLint);
using PFNGLCHECKFRAMEBUFFERSTATUSPROC = GLenum (*)(GLenum);

PFNGLGENBUFFERSPROC glGenBuffers_ = nullptr;
PFNGLBINDBUFFERPROC glBindBuffer_ = nullptr;
PFNGLBUFFERDATAPROC glBufferData_ = nullptr;
PFNGLGENVERTEXARRAYSPROC glGenVertexArrays_ = nullptr;
PFNGLBINDVERTEXARRAYPROC glBindVertexArray_ = nullptr;
PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_ = nullptr;
PFNGLVERTEXATTRIBPOINTERPROC glVertexAttribPointer_ = nullptr;
PFNGLCREATESHADERPROC glCreateShader_ = nullptr;
PFNGLSHADERSOURCEPROC glShaderSource_ = nullptr;
PFNGLCOMPILESHADERPROC glCompileShader_ = nullptr;
PFNGLGETSHADERIVPROC glGetShaderiv_ = nullptr;
PFNGLGETSHADERINFOLOGPROC glGetShaderInfoLog_ = nullptr;
PFNGLCREATEPROGRAMPROC glCreateProgram_ = nullptr;
PFNGLATTACHSHADERPROC glAttachShader_ = nullptr;
PFNGLBINDATTRIBLOCATIONPROC glBindAttribLocation_ = nullptr;
PFNGLLINKPROGRAMPROC glLinkProgram_ = nullptr;
PFNGLGETPROGRAMIVPROC glGetProgramiv_ = nullptr;
PFNGLGETPROGRAMINFOLOGPROC glGetProgramInfoLog_ = nullptr;
PFNGLUSEPROGRAMPROC glUseProgram_ = nullptr;
PFNGLGETUNIFORMLOCATIONPROC glGetUniformLocation_ = nullptr;
PFNGLUNIFORM1IPROC glUniform1i_ = nullptr;
PFNGLUNIFORM1FPROC glUniform1f_ = nullptr;
PFNGLUNIFORM2FPROC glUniform2f_ = nullptr;
PFNGLUNIFORM4FPROC glUniform4f_ = nullptr;
PFNGLUNIFORMMATRIX4FVPROC glUniformMatrix4fv_ = nullptr;
PFNGLACTIVETEXTUREPROC glActiveTexture_ = nullptr;
PFNGLGENFRAMEBUFFERSPROC glGenFramebuffers_ = nullptr;
PFNGLBINDFRAMEBUFFERPROC glBindFramebuffer_ = nullptr;
PFNGLFRAMEBUFFERTEXTURE2DPROC glFramebufferTexture2D_ = nullptr;
PFNGLCHECKFRAMEBUFFERSTATUSPROC glCheckFramebufferStatus_ = nullptr;

/**
 * Loads every GL entry point this test rig needs beyond the fixed GL 1.1 core
 * (which <GL/gl.h> declares directly), via eglGetProcAddress().
 *
 * Returns:
 *   true if every function pointer was resolved, false (with a message on
 *   stderr naming the missing one) otherwise.
 */
bool loadGlFunctions()
{
    struct Entry
    {
        void **target;
        const char *name;
    };
    // WHY a table instead of one reinterpret_cast line per function: keeps the
    // "did we find every one of these" check in a single loop instead of N
    // repeated if-checks that are easy to accidentally skip when adding a new
    // function later.
    const Entry entries[] = {
        {reinterpret_cast<void **>(&glGenBuffers_), "glGenBuffers"},
        {reinterpret_cast<void **>(&glBindBuffer_), "glBindBuffer"},
        {reinterpret_cast<void **>(&glBufferData_), "glBufferData"},
        {reinterpret_cast<void **>(&glGenVertexArrays_), "glGenVertexArrays"},
        {reinterpret_cast<void **>(&glBindVertexArray_), "glBindVertexArray"},
        {reinterpret_cast<void **>(&glEnableVertexAttribArray_), "glEnableVertexAttribArray"},
        {reinterpret_cast<void **>(&glVertexAttribPointer_), "glVertexAttribPointer"},
        {reinterpret_cast<void **>(&glCreateShader_), "glCreateShader"},
        {reinterpret_cast<void **>(&glShaderSource_), "glShaderSource"},
        {reinterpret_cast<void **>(&glCompileShader_), "glCompileShader"},
        {reinterpret_cast<void **>(&glGetShaderiv_), "glGetShaderiv"},
        {reinterpret_cast<void **>(&glGetShaderInfoLog_), "glGetShaderInfoLog"},
        {reinterpret_cast<void **>(&glCreateProgram_), "glCreateProgram"},
        {reinterpret_cast<void **>(&glAttachShader_), "glAttachShader"},
        {reinterpret_cast<void **>(&glBindAttribLocation_), "glBindAttribLocation"},
        {reinterpret_cast<void **>(&glLinkProgram_), "glLinkProgram"},
        {reinterpret_cast<void **>(&glGetProgramiv_), "glGetProgramiv"},
        {reinterpret_cast<void **>(&glGetProgramInfoLog_), "glGetProgramInfoLog"},
        {reinterpret_cast<void **>(&glUseProgram_), "glUseProgram"},
        {reinterpret_cast<void **>(&glGetUniformLocation_), "glGetUniformLocation"},
        {reinterpret_cast<void **>(&glUniform1i_), "glUniform1i"},
        {reinterpret_cast<void **>(&glUniform1f_), "glUniform1f"},
        {reinterpret_cast<void **>(&glUniform2f_), "glUniform2f"},
        {reinterpret_cast<void **>(&glUniform4f_), "glUniform4f"},
        {reinterpret_cast<void **>(&glUniformMatrix4fv_), "glUniformMatrix4fv"},
        {reinterpret_cast<void **>(&glActiveTexture_), "glActiveTexture"},
        {reinterpret_cast<void **>(&glGenFramebuffers_), "glGenFramebuffers"},
        {reinterpret_cast<void **>(&glBindFramebuffer_), "glBindFramebuffer"},
        {reinterpret_cast<void **>(&glFramebufferTexture2D_), "glFramebufferTexture2D"},
        {reinterpret_cast<void **>(&glCheckFramebufferStatus_), "glCheckFramebufferStatus"},
    };
    for (const Entry &entry : entries) {
        *entry.target = reinterpret_cast<void *>(eglGetProcAddress(entry.name));
        if (*entry.target == nullptr) {
            std::fprintf(stderr, "failed to load GL function: %s\n", entry.name);
            return false;
        }
    }
    return true;
}

constexpr int kWindowWidth = 100;
constexpr int kWindowHeight = 50;
constexpr int kGradientTextureSize = 512;
constexpr int kNoiseTextureSize = 64;
// See this file's own top comment for the full error-budget derivation.
constexpr double kEpsilonBytes = 3.0;

/**
 * Builds the 512x512 RGBA8 "UV gradient" texture described in this file's own
 * top comment: texel (tx, ty) stores its own centre UV coordinate, scaled to a
 * byte, in R (u) and G (v); B is a constant marker; A is always opaque.
 */
std::vector<uint8_t> buildGradientTexture()
{
    std::vector<uint8_t> pixels(static_cast<size_t>(kGradientTextureSize) * kGradientTextureSize * 4);
    for (int ty = 0; ty < kGradientTextureSize; ++ty) {
        const double vCenter = (ty + 0.5) / kGradientTextureSize;
        for (int tx = 0; tx < kGradientTextureSize; ++tx) {
            const double uCenter = (tx + 0.5) / kGradientTextureSize;
            const size_t offset = (static_cast<size_t>(ty) * kGradientTextureSize + tx) * 4;
            pixels[offset + 0] = static_cast<uint8_t>(std::lround(uCenter * 255.0));
            pixels[offset + 1] = static_cast<uint8_t>(std::lround(vCenter * 255.0));
            pixels[offset + 2] = 128;
            pixels[offset + 3] = 255;
        }
    }
    return pixels;
}

/** Builds a small, single-channel (GL_RED) tiled noise texture, same technique
 * frost.cpp's own generateNoiseTexture() uses, just at a smaller resolution
 * (this test only checks the noise contribution's BOUNDS, never an exact
 * value, so the tile size and its exact random content do not matter -- see
 * expectNoiseBounded in main()).
 */
std::vector<uint8_t> buildNoiseTexture()
{
    std::vector<uint8_t> pixels(static_cast<size_t>(kNoiseTextureSize) * kNoiseTextureSize);
    unsigned seed = 12345u; // fixed, arbitrary: determinism is irrelevant here, only boundedness is checked.
    for (uint8_t &texel : pixels) {
        seed = seed * 1103515245u + 12345u;
        texel = static_cast<uint8_t>((seed >> 16) & 0xFF);
    }
    return pixels;
}

GLuint compileShader(GLenum type, const char *source)
{
    const GLuint shader = glCreateShader_(type);
    glShaderSource_(shader, 1, &source, nullptr);
    glCompileShader_(shader);
    GLint compiled = GL_FALSE;
    glGetShaderiv_(shader, GL_COMPILE_STATUS, &compiled);
    if (compiled == GL_FALSE) {
        char log[4096];
        GLsizei logLength = 0;
        glGetShaderInfoLog_(shader, sizeof(log), &logLength, log);
        std::fprintf(stderr, "shader compile failed: %.*s\n", logLength, log);
    }
    return compiled == GL_TRUE ? shader : 0;
}

struct SampledPixel
{
    double r; // 0..255
    double g;
    double b;
    double a;
};

/** Reads back one pixel from the currently bound framebuffer as normalized 0..255 doubles. */
SampledPixel readPixel(int x, int y)
{
    uint8_t rgba[4] = {0, 0, 0, 0};
    glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    return SampledPixel{static_cast<double>(rgba[0]), static_cast<double>(rgba[1]), static_cast<double>(rgba[2]), static_cast<double>(rgba[3])};
}

bool nearlyEqual(double actual, double expected, const char *label, bool &allPassed)
{
    const double delta = std::fabs(actual - expected);
    const bool ok = delta <= kEpsilonBytes;
    std::printf("  %-28s expected=%7.3f actual=%7.3f delta=%6.3f %s\n", label, expected, actual, delta, ok ? "OK" : "FAIL");
    if (!ok) {
        allPassed = false;
    }
    return ok;
}

} // namespace

int main()
{
    // ---- 1. Headless EGL/GL context (mesa's software rasterizer) ----
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (display == EGL_NO_DISPLAY) {
        std::fprintf(stderr, "eglGetDisplay failed\n");
        return EXIT_FAILURE;
    }
    EGLint eglMajor = 0;
    EGLint eglMinor = 0;
    if (eglInitialize(display, &eglMajor, &eglMinor) == EGL_FALSE) {
        std::fprintf(stderr, "eglInitialize failed\n");
        return EXIT_FAILURE;
    }
    if (eglBindAPI(EGL_OPENGL_API) == EGL_FALSE) {
        std::fprintf(stderr, "eglBindAPI(EGL_OPENGL_API) failed\n");
        return EXIT_FAILURE;
    }

    const EGLint configAttribs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_NONE,
    };
    EGLConfig config = nullptr;
    EGLint numConfigs = 0;
    if (eglChooseConfig(display, configAttribs, &config, 1, &numConfigs) == EGL_FALSE || numConfigs == 0) {
        std::fprintf(stderr, "eglChooseConfig failed\n");
        return EXIT_FAILURE;
    }

    // A pbuffer surface is only needed to satisfy eglMakeCurrent's requirement
    // for a valid surface -- the actual test rendering happens into Frost's
    // own FBO/texture, created below, not onto this surface's own framebuffer.
    const EGLint pbufferAttribs[] = {EGL_WIDTH, kWindowWidth, EGL_HEIGHT, kWindowHeight, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, pbufferAttribs);
    if (surface == EGL_NO_SURFACE) {
        std::fprintf(stderr, "eglCreatePbufferSurface failed\n");
        return EXIT_FAILURE;
    }

    // #version 140 (GLSL 1.40) corresponds to OpenGL 3.1 -- request that.
    const EGLint contextAttribs[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 1, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttribs);
    if (context == EGL_NO_CONTEXT) {
        std::fprintf(stderr, "eglCreateContext failed\n");
        return EXIT_FAILURE;
    }
    if (eglMakeCurrent(display, surface, surface, context) == EGL_FALSE) {
        std::fprintf(stderr, "eglMakeCurrent failed\n");
        return EXIT_FAILURE;
    }

    if (!loadGlFunctions()) {
        return EXIT_FAILURE;
    }

    // ---- 2. Compile/link the REAL shader pair (shared with frost.cpp) ----
    const GLuint vertexShader = compileShader(GL_VERTEX_SHADER, Kuura::kFrostTestVertexShaderSource);
    const GLuint fragmentShader = compileShader(GL_FRAGMENT_SHADER, Kuura::kFrostFragmentShaderSource);
    if (vertexShader == 0 || fragmentShader == 0) {
        return EXIT_FAILURE;
    }
    const GLuint program = glCreateProgram_();
    glAttachShader_(program, vertexShader);
    glAttachShader_(program, fragmentShader);
    glBindAttribLocation_(program, 0, "position");
    glBindAttribLocation_(program, 1, "texcoord");
    glLinkProgram_(program);
    GLint linked = GL_FALSE;
    glGetProgramiv_(program, GL_LINK_STATUS, &linked);
    if (linked == GL_FALSE) {
        char log[4096];
        GLsizei logLength = 0;
        glGetProgramInfoLog_(program, sizeof(log), &logLength, log);
        std::fprintf(stderr, "program link failed: %.*s\n", logLength, log);
        return EXIT_FAILURE;
    }
    glUseProgram_(program);

    // ---- 3. Full-screen quad (see this file's own top comment for the
    // texcoord <-> window pixel convention this vertex data establishes) ----
    const float vertices[] = {
        // position (vec4)      texcoord (vec4)
        -1.0F, -1.0F, 0.0F, 1.0F, 0.0F, 0.0F, 0.0F, 1.0F,
        -1.0F, 1.0F, 0.0F, 1.0F, 0.0F, 1.0F, 0.0F, 1.0F,
        1.0F, -1.0F, 0.0F, 1.0F, 1.0F, 0.0F, 0.0F, 1.0F,
        1.0F, 1.0F, 0.0F, 1.0F, 1.0F, 1.0F, 0.0F, 1.0F,
    };
    GLuint vao = 0;
    glGenVertexArrays_(1, &vao);
    glBindVertexArray_(vao);
    GLuint vbo = 0;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, static_cast<ptrdiff_t>(sizeof(vertices)), vertices, GL_STATIC_DRAW);
    glEnableVertexAttribArray_(0);
    glVertexAttribPointer_(0, 4, GL_FLOAT, GL_FALSE, 8 * sizeof(float), reinterpret_cast<const void *>(0));
    glEnableVertexAttribArray_(1);
    glVertexAttribPointer_(1, 4, GL_FLOAT, GL_FALSE, 8 * sizeof(float), reinterpret_cast<const void *>(4 * sizeof(float)));

    // ---- 4. Input textures: the known UV gradient (unit 0) and the noise
    // tile (unit 1) -- matching frost.cpp's own real unit assignment. ----
    const std::vector<uint8_t> gradient = buildGradientTexture();
    GLuint gradientTexture = 0;
    glGenTextures(1, &gradientTexture);
    glActiveTexture_(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, gradientTexture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kGradientTextureSize, kGradientTextureSize, 0, GL_RGBA, GL_UNSIGNED_BYTE, gradient.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    const std::vector<uint8_t> noise = buildNoiseTexture();
    GLuint noiseTexture = 0;
    glGenTextures(1, &noiseTexture);
    glActiveTexture_(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, noiseTexture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RED, kNoiseTextureSize, kNoiseTextureSize, 0, GL_RED, GL_UNSIGNED_BYTE, noise.data());
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);

    // ---- 5. Output FBO (100x50, matching windowSize exactly -- see this
    // file's own top comment) ----
    GLuint outputTexture = 0;
    glGenTextures(1, &outputTexture);
    glBindTexture(GL_TEXTURE_2D, outputTexture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kWindowWidth, kWindowHeight, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    GLuint fbo = 0;
    glGenFramebuffers_(1, &fbo);
    glBindFramebuffer_(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, outputTexture, 0);
    if (glCheckFramebufferStatus_(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        std::fprintf(stderr, "framebuffer incomplete\n");
        return EXIT_FAILURE;
    }
    glViewport(0, 0, kWindowWidth, kWindowHeight);

    // ---- 6. Uniforms. Real material.* values come from the SAME generated
    // header frost.cpp itself consumes (<tokens.h>, design/tokens.json via
    // design/generators/cpp_header.py) -- not re-typed literals, so this test
    // stays in sync with tokens.json exactly like the real plugin does. ----
    glUniform1i_(glGetUniformLocation_(program, "sampler"), 0);
    glUniform1i_(glGetUniformLocation_(program, "noiseSampler"), 1);
    glUniform1i_(glGetUniformLocation_(program, "textureWidth"), kWindowWidth);
    glUniform1i_(glGetUniformLocation_(program, "textureHeight"), kWindowHeight);
    glUniform2f_(glGetUniformLocation_(program, "noiseTextureSize"), static_cast<float>(kNoiseTextureSize), static_cast<float>(kNoiseTextureSize));
    glUniform1f_(glGetUniformLocation_(program, "edgeHighlightWidth"), Kuura::Tokens::kMaterialEdgeHighlightWidth);
    glUniform1f_(glGetUniformLocation_(program, "edgeHighlightOpacity"), Kuura::Tokens::kMaterialEdgeHighlightOpacity);
    const GLint noiseAmountLocation = glGetUniformLocation_(program, "noiseAmount");
    glUniform1f_(glGetUniformLocation_(program, "lightRimOpacity"), Kuura::Tokens::kMaterialEdgeHighlightLightHairlineOpacity);
    glUniform1f_(glGetUniformLocation_(program, "lightRimWidth"), Kuura::Tokens::kMaterialEdgeHighlightLightHairlineWidth);
    const GLint lumaLowLocation = glGetUniformLocation_(program, "lightRimLumaLow");
    const GLint lumaHighLocation = glGetUniformLocation_(program, "lightRimLumaHigh");
    // Passes 1-5 test geometry (edges, orientation, highlight, premultiplied
    // coverage) on a UV-gradient input whose luma spans the light-rim ramp, so
    // the light-surface rim would otherwise switch on partially at some pixels.
    // A ramp of [2, 3] is above any possible luma (<= 1): light weight is
    // exactly 0 there. Passes 6-7 use the REAL thresholds.
    const auto setLightRimRamp = [lumaLowLocation, lumaHighLocation](float low, float high) {
        glUniform1f_(lumaLowLocation, low);
        glUniform1f_(lumaHighLocation, high);
    };
    setLightRimRamp(2.0F, 3.0F);
    // modulation defaults to (0,0,0,0) if never set (its uniform location
    // resolves fine since the real shader declares it) -- must be identity
    // (1,1,1,1) here, since this test is isolating the material math itself,
    // not KWin's own separate opacity/brightness pipeline (which frost.h's
    // apply() docstring does not ask this shader to reimplement).
    glUniform4f_(glGetUniformLocation_(program, "modulation"), 1.0F, 1.0F, 1.0F, 1.0F);

    // This test's own vertex shader (frost_shader.h's kFrostTestVertexShaderSource,
    // copied from KWin's real base.vert) transforms every vertex by
    // modelViewProjectionMatrix. A real KWin session's ShaderManager uploads a
    // real projection there every frame; this standalone rig has no such
    // pipeline, so it must set one explicitly -- an IDENTITY matrix is exactly
    // right here since the vertex data above is already authored directly in
    // clip-space NDC ([-1,1]). Leaving this uniform unset would leave it at
    // GLSL's own default-zero-initialized mat4, collapsing every vertex to clip
    // -space (0,0,0,0) -- a degenerate, zero-area triangle strip that rasterizes
    // no fragments at all (silently reading back only the glClear colour).
    const GLfloat identityMvp[16] = {
        1.0F, 0.0F, 0.0F, 0.0F,
        0.0F, 1.0F, 0.0F, 0.0F,
        0.0F, 0.0F, 1.0F, 0.0F,
        0.0F, 0.0F, 0.0F, 1.0F,
    };
    glUniformMatrix4fv_(glGetUniformLocation_(program, "modelViewProjectionMatrix"), 1, GL_FALSE, identityMvp);

    const GLint glassRectLocation = glGetUniformLocation_(program, "glassRect");
    glUniform4f_(glassRectLocation, 0.0F, 0.0F, static_cast<float>(kWindowWidth), static_cast<float>(kWindowHeight));

    bool allPassed = true;

    // Draws the full-screen quad once with the current uniforms/textures.
    const auto draw = []() {
        glClearColor(0.0F, 0.0F, 0.0F, 0.0F);
        glClear(GL_COLOR_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    };
    // Compares one read-back pixel against four hand-computed channel values.
    const auto expectPixel = [&allPassed](const char *title, int px, int py, double r, double g, double b, double a) {
        std::printf("%s (%d,%d):\n", title, px, py);
        const SampledPixel pixel = readPixel(px, py);
        nearlyEqual(pixel.r, r, "R", allPassed);
        nearlyEqual(pixel.g, g, "G", allPassed);
        nearlyEqual(pixel.b, b, "B", allPassed);
        nearlyEqual(pixel.a, a, "A", allPassed);
    };

    // =========================================================================
    // PASS 1: glassRect = whole texture, noiseAmount = 0, so every check is
    // fully deterministic (apply() docstring points 1-3).
    // Shared numbers: refraction max = strength*edge_falloff = 0.035*12 = 0.42px;
    // The highlight width and opacity are the REAL tokens, so the expected
    // values below are derived from them instead of being pinned to one pair
    // of numbers (a deliberate material retune must not need a test edit):
    // at pixelPos 0.5 from a lit edge, highlight = 1 - 0.5/width and the mix
    // factor is k = highlight * opacity; an opaque (a=255) input mixes toward
    // 255 (premultiplied white at full coverage). The worked examples in the
    // comments below use the original tokens (width 1.0, opacity 0.28 ->
    // highlight 0.5, k = 0.14); the arithmetic is the same for any tokens.
    // Sample positions are clamped into [0.5, size-0.5] of the glass rect.
    // =========================================================================
    glUniform1f_(noiseAmountLocation, 0.0F);
    draw();
    const double highlightK =
        (1.0 - 0.5 / static_cast<double>(Kuura::Tokens::kMaterialEdgeHighlightWidth)) * Kuura::Tokens::kMaterialEdgeHighlightOpacity;
    // Mixes one channel toward the (premultiplied) white level `whiteLevel`.
    const auto mixK = [highlightK](double channel, double whiteLevel) { return channel * (1.0 - highlightK) + whiteLevel * highlightK; };

    // ---- TOP-LEFT CORNER: readPixel(0, 49) -> pixelPos = (0.5, 0.5) ----
    // distLeft = distTop = 0.5 (tie -> LEFT, checked first), normal (-1, 0).
    // falloff = 1 - 0.5/12 = 0.958333; offset = -0.42*0.958333 = -0.4025px
    // sampleLocal = clamp((0.0975, 0.5), 0.5, ...) = (0.5, 0.5) -- the clamp
    // keeps the sample inside the glass, so no net displacement here.
    // refractedUv = (0.5/100, 1 - 0.5/50) = (0.005, 0.99)
    // refracted = (0.005*255, 0.99*255, 128) = (1.275, 252.45, 128)
    // highlight max(0.5, 0.5) = 0.5 -> k = 0.14:
    //   r = 1.275*0.86 + 255*0.14 = 1.0965 + 35.7 = 36.797
    //   g = 252.45*0.86 + 35.7 = 217.107 + 35.7 = 252.807
    //   b = 128*0.86 + 35.7 = 110.08 + 35.7 = 145.78
    expectPixel("TOP-LEFT CORNER", 0, 49, mixK(1.275, 255.0), mixK(252.45, 255.0), mixK(128.0, 255.0), 255.0);

    // ---- TOP EDGE: readPixel(50, 49) -> pixelPos = (50.5, 0.5) ----
    // Proves the orientation: the window's TOP edge (lit) is row 49.
    // distTop = 0.5 -> normal (0, -1); offset y = -0.4025 -> clamped to 0.5.
    // refractedUv = (0.505, 0.99) -> (128.775, 252.45, 128)
    // highlight: top 0.5, left 0 -> k = 0.14:
    //   r = 128.775*0.86 + 35.7 = 110.7465 + 35.7 = 146.447
    //   g = 252.807, b = 145.78 (as above)
    expectPixel("TOP EDGE", 50, 49, mixK(128.775, 255.0), mixK(252.45, 255.0), mixK(128.0, 255.0), 255.0);

    // ---- BOTTOM EDGE: readPixel(50, 0) -> pixelPos = (50.5, 49.5) ----
    // Unlit edge: NO highlight. distBottom = 0.5 -> normal (0, 1);
    // offset y = +0.4025 -> 49.9025 -> clamped to 49.5.
    // refractedUv = (0.505, 1 - 49.5/50) = (0.505, 0.01) -> (128.775, 2.55, 128)
    expectPixel("BOTTOM EDGE", 50, 0, 128.775, 2.55, 128.0, 255.0);

    // ---- NEAR-BOTTOM, NO WINDOW DISPLACEMENT: readPixel(50, 5) -> pixelPos = (50.5, 44.5) ----
    // REQUIREMENT CHANGE 2026-10-20: refraction now displaces the BACKDROP
    // (PASS 8), not the window's own content. This pixel is inside the
    // refraction falloff (distBottom = 5.5 < edge_falloff) and the former
    // shader sampled 0.2275 px lower here (g = 26.890); it must now be an
    // unmodified sample at texcoord0 = (0.505, 0.11) -> r = 128.775, g = 28.05.
    expectPixel("NEAR-BOTTOM NO DISPLACEMENT", 50, 5, 128.775, 28.05, 128.0, 255.0);

    // ---- CENTRE: readPixel(50, 25) -> pixelPos = (50.5, 24.5) ----
    // edgeDist = min(50.5, 49.5, 24.5, 25.5) = 24.5 > 12 -> no refraction, no
    // highlight: an unmodified sample at texcoord0 = (0.505, 0.51).
    expectPixel("CENTRE", 50, 25, 128.775, 130.05, 128.0, 255.0);
    const SampledPixel centreNoNoise = readPixel(50, 25);

    // =========================================================================
    // PASS 2: noiseAmount = the REAL token value (Kuura::Tokens::kMaterialNoise),
    // same centre pixel. Noise is random by design, so only its formula's
    // BOUNDS are checked: delta = noiseSample * noiseAmount * alpha with
    // noiseSample in [0, 1) and alpha = 1 here -> 0 <= delta < noiseAmount*255.
    // =========================================================================
    glUniform1f_(noiseAmountLocation, Kuura::Tokens::kMaterialNoise);
    draw();
    const auto expectNoiseBounded = [&allPassed](const char *title, const SampledPixel &with, const SampledPixel &without, double maxDelta) {
        std::printf("%s (bounded-delta check, max %.3f):\n", title, maxDelta);
        for (const auto &[label, withNoise, withoutNoise] : {
                 std::tuple{"R", with.r, without.r},
                 std::tuple{"G", with.g, without.g},
                 std::tuple{"B", with.b, without.b},
             }) {
            const double delta = withNoise - withoutNoise;
            const bool ok = delta >= -kEpsilonBytes && delta <= maxDelta + kEpsilonBytes;
            std::printf("  %-28s delta=%7.3f bounds=[%.3f, %.3f] %s\n", label, delta, -kEpsilonBytes, maxDelta + kEpsilonBytes, ok ? "OK" : "FAIL");
            if (!ok) {
                allPassed = false;
            }
        }
    };
    expectNoiseBounded("CENTRE WITH NOISE", readPixel(50, 25), centreNoNoise, Kuura::Tokens::kMaterialNoise * 255.0);

    // =========================================================================
    // PASS 3: glassRect = (20, 10, 60, 30) -- a strict sub-rect, the real
    // situation (the capture texture includes the shadow margin around the
    // glass). Edges are those of the RECT; outside it the texture passes
    // through unmodified -- not even noise (noiseAmount stays non-zero here on
    // purpose, so a leak would show up as a non-zero delta).
    // =========================================================================
    glUniform4f_(glassRectLocation, 20.0F, 10.0F, 60.0F, 30.0F);
    draw();

    // ---- OUTSIDE (shadow margin): readPixel(5, 25) -> pixelPos = (5.5, 24.5) ----
    // local.x = -14.5 < 0 -> passthrough of texcoord0 = (0.055, 0.51):
    //   r = 0.055*255 = 14.025, g = 130.05, b = 128 -- exact, no noise added.
    // (Pass 1's shader geometry would have refracted AND, near the old texture
    // edge, highlighted this pixel; that is exactly the shadow-edge artefact.)
    expectPixel("OUTSIDE GLASS RECT", 5, 25, 14.025, 130.05, 128.0, 255.0);

    glUniform1f_(noiseAmountLocation, 0.0F);
    draw();

    // ---- GLASS TOP-LEFT CORNER: readPixel(20, 39) -> pixelPos = (20.5, 10.5) ----
    // local = (0.5, 0.5) -> as pass 1's corner, the sample clamps to local
    // (0.5, 0.5) = pixelPos (20.5, 10.5) -> uv (0.205, 1 - 0.21) = (0.205, 0.79)
    // refracted = (52.275, 201.45, 128); k = 0.14:
    //   r = 52.275*0.86 + 35.7 = 44.9565 + 35.7 = 80.657
    //   g = 201.45*0.86 + 35.7 = 173.247 + 35.7 = 208.947
    //   b = 145.78
    expectPixel("GLASS TOP-LEFT CORNER", 20, 39, mixK(52.275, 255.0), mixK(201.45, 255.0), mixK(128.0, 255.0), 255.0);

    // ---- NEAR GLASS RIGHT EDGE: readPixel(75, 24) -> pixelPos = (75.5, 25.5) ----
    // local = (55.5, 15.5): 4.5 px from the glass rect's right edge, inside the
    // refraction falloff. Former expectation (window content refracted 0.2625
    // px outward): r = 193.194. Now unmodified: uv (0.755, 0.49) ->
    //   r = 0.755*255 = 192.525, g = 124.95, b = 128; no highlight.
    expectPixel("NEAR GLASS RIGHT EDGE", 75, 24, 192.525, 124.95, 128.0, 255.0);

    // =========================================================================
    // PASS 4: glassRect all zero (the GLSL default before Frost::apply() has
    // uploaded one) -> the material is disabled, everything passes through.
    // readPixel(0, 49): texcoord0 = (0.005, 0.99) -> (1.275, 252.45, 128) with
    // no highlight (pass 1 put 36.797/252.807/145.78 here).
    // =========================================================================
    glUniform4f_(glassRectLocation, 0.0F, 0.0F, 0.0F, 0.0F);
    draw();
    expectPixel("ZERO GLASS RECT PASSTHROUGH", 0, 49, 1.275, 252.45, 128.0, 255.0);

    // =========================================================================
    // PASS 5: PREMULTIPLIED, HALF-COVERED input. The capture is premultiplied
    // (OffscreenData::paint() blends GL_ONE, GL_ONE_MINUS_SRC_ALPHA), so the
    // highlight must mix toward (a, a, a), not 255, and noise must scale with
    // a -- otherwise a transparent texel (a rounded corner inside the
    // bounding rect) would emit light over Blur's backdrop.
    // Input: a uniform premultiplied (64, 64, 64, 128) texture.
    // =========================================================================
    {
        std::vector<uint8_t> pixels(static_cast<size_t>(kGradientTextureSize) * kGradientTextureSize * 4, 0);
        for (size_t i = 0; i < pixels.size(); i += 4) {
            pixels[i + 0] = 64;
            pixels[i + 1] = 64;
            pixels[i + 2] = 64;
            pixels[i + 3] = 128;
        }
        glActiveTexture_(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, gradientTexture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kGradientTextureSize, kGradientTextureSize, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    }
    glUniform4f_(glassRectLocation, 0.0F, 0.0F, static_cast<float>(kWindowWidth), static_cast<float>(kWindowHeight));
    glUniform1f_(noiseAmountLocation, 0.0F);
    draw();
    // Corner k = 0.14: rgb = 64*0.86 + 128*0.14 = 55.04 + 17.92 = 72.96; a = 128.
    // (Mixing toward 255 instead would give 90.74 -- outside the epsilon.)
    expectPixel("HALF-COVERED CORNER", 0, 49, mixK(64.0, 128.0), mixK(64.0, 128.0), mixK(64.0, 128.0), 128.0);
    const SampledPixel halfCentreNoNoise = readPixel(50, 25);
    glUniform1f_(noiseAmountLocation, Kuura::Tokens::kMaterialNoise);
    draw();
    // Noise delta bound scales with coverage: noiseAmount * 255 * (128/255).
    expectNoiseBounded("HALF-COVERED CENTRE WITH NOISE", readPixel(50, 25), halfCentreNoNoise, Kuura::Tokens::kMaterialNoise * 128.0);

    // =========================================================================
    // PASSES 6-7: LIGHT-SURFACE RIM (requirement change 2026-10-20). Real
    // thresholds from here on. Inputs are uniform premultiplied surfaces at the
    // panel token's coverage (bg_opacity.panel 0.62 -> a = 158 of 255), with
    // the noise off so every value is deterministic. Expected values come from
    // windowRim() below -- the shader's own formula written out in C++ from
    // the token values -- and, for "unchanged in dark mode", from oldRim(),
    // the pre-change formula.
    // =========================================================================
    setLightRimRamp(Kuura::Tokens::kMaterialEdgeHighlightLightLumaLow, Kuura::Tokens::kMaterialEdgeHighlightLightLumaHigh);
    glUniform1f_(noiseAmountLocation, 0.0F);
    glUniform4f_(glassRectLocation, 0.0F, 0.0F, static_cast<float>(kWindowWidth), static_cast<float>(kWindowHeight));

    const double highlightWidth = Kuura::Tokens::kMaterialEdgeHighlightWidth;
    const double highlightOpacity = Kuura::Tokens::kMaterialEdgeHighlightOpacity;
    const double rimWidth = Kuura::Tokens::kMaterialEdgeHighlightLightHairlineWidth;
    const double rimOpacity = Kuura::Tokens::kMaterialEdgeHighlightLightHairlineOpacity;
    // GLSL smoothstep(), for the light weight.
    const auto smoothstep = [](double edge0, double edge1, double x) {
        const double t = std::clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0);
        return t * t * (3.0 - 2.0 * t);
    };
    // The PRE-CHANGE highlight: mix toward (a, a, a) by clamp(1 - d / width)
    // * opacity, d = distance from the top or left edge (max of the two).
    const auto oldRim = [&](double c, double a, double lx, double ly) {
        const double hl = std::max(std::clamp(1.0 - ly / highlightWidth, 0.0, 1.0), std::clamp(1.0 - lx / highlightWidth, 0.0, 1.0));
        return c + (a - c) * hl * highlightOpacity;
    };
    // The NEW rim for one grey premultiplied channel c at coverage a, at
    // glass-local position (lx, ly) of a kWindowWidth x kWindowHeight glass.
    const auto windowRim = [&](double c, double a, double lx, double ly) {
        const double weight = smoothstep(Kuura::Tokens::kMaterialEdgeHighlightLightLumaLow, Kuura::Tokens::kMaterialEdgeHighlightLightLumaHigh, c / a);
        const double shift = weight * rimWidth;
        const auto lit = [&](double d) { return d >= 0.0 ? std::clamp(1.0 - d / highlightWidth, 0.0, 1.0) : 0.0; };
        const double hl = std::max(lit(ly - shift), lit(lx - shift));
        const double highlighted = c + (a - c) * hl * highlightOpacity;
        const double edgeDist = std::min(std::min(lx, kWindowWidth - lx), std::min(ly, kWindowHeight - ly));
        const double hairline = std::clamp(rimWidth - edgeDist + 0.5, 0.0, 1.0) * weight;
        return highlighted * (1.0 - hairline * rimOpacity);
    };
    // Fills the input texture with one uniform premultiplied grey.
    const auto uploadUniformGrey = [gradientTexture](uint8_t c, uint8_t a) {
        std::vector<uint8_t> pixels(static_cast<size_t>(kGradientTextureSize) * kGradientTextureSize * 4, 0);
        for (size_t i = 0; i < pixels.size(); i += 4) {
            pixels[i + 0] = c;
            pixels[i + 1] = c;
            pixels[i + 2] = c;
            pixels[i + 3] = a;
        }
        glActiveTexture_(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, gradientTexture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, kGradientTextureSize, kGradientTextureSize, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    };
    const auto expectGrey = [&allPassed](const char *title, int px, int py, double c, double a) {
        std::printf("%s (%d,%d):\n", title, px, py);
        const SampledPixel pixel = readPixel(px, py);
        nearlyEqual(pixel.r, c, "R", allPassed);
        nearlyEqual(pixel.g, c, "G", allPassed);
        nearlyEqual(pixel.b, c, "B", allPassed);
        nearlyEqual(pixel.a, a, "A", allPassed);
    };
    constexpr double kPanelAlpha = 158.0; // round(0.62 * 255)

    // ---- PASS 6: DARK surface, colour 0.13 (c = round(0.13 * 158) = 21):
    // luma 21/158 = 0.133, far below kLightRimLumaLow -> weight exactly 0, so
    // the output must equal the PRE-CHANGE formula pixel for pixel. ----
    {
        constexpr double c = 21.0;
        uploadUniformGrey(21, 158);
        draw();
        expectGrey("DARK TOP-LEFT CORNER (unchanged)", 0, 49, oldRim(c, kPanelAlpha, 0.5, 0.5), kPanelAlpha);
        expectGrey("DARK TOP EDGE (unchanged)", 50, 49, oldRim(c, kPanelAlpha, 50.5, 0.5), kPanelAlpha);
        expectGrey("DARK 2ND ROW (unchanged)", 50, 48, oldRim(c, kPanelAlpha, 50.5, 1.5), kPanelAlpha);
        // No dark hairline on the bottom/right edges in dark mode.
        expectGrey("DARK BOTTOM EDGE (no hairline)", 50, 0, c, kPanelAlpha);
        expectGrey("DARK RIGHT EDGE (no hairline)", 99, 25, c, kPanelAlpha);
    }

    // ---- PASS 7: LIGHT surface, colour 0.94 (c = round(0.94 * 158) = 149),
    // composited (on the CPU, exactly as GL_ONE, GL_ONE_MINUS_SRC_ALPHA would)
    // over a near-white frosted backdrop of 245. ----
    {
        constexpr double c = 149.0;
        constexpr double backdrop = 245.0;
        const auto composite = [backdrop](double premultiplied) { return premultiplied + backdrop * (255.0 - kPanelAlpha) / 255.0; };
        uploadUniformGrey(149, 158);
        draw();
        expectGrey("LIGHT TOP EDGE (hairline)", 50, 49, windowRim(c, kPanelAlpha, 50.5, 0.5), kPanelAlpha);
        expectGrey("LIGHT 2ND ROW (shifted highlight)", 50, 48, windowRim(c, kPanelAlpha, 50.5, 1.5), kPanelAlpha);
        expectGrey("LIGHT BOTTOM EDGE (hairline)", 50, 0, windowRim(c, kPanelAlpha, 50.5, 49.5), kPanelAlpha);
        expectGrey("LIGHT CENTRE (untouched)", 50, 25, c, kPanelAlpha);

        // Contrast of the top rim row against the interior, on screen. The
        // backdrop term is identical for both pixels and cancels; it is kept
        // so the printed numbers are the real on-screen levels.
        const double interior = composite(readPixel(50, 25).r);
        const double newContrast = std::fabs(composite(readPixel(50, 49).r) - interior);
        const double oldContrast = std::fabs(composite(oldRim(c, kPanelAlpha, 50.5, 0.5)) - composite(c));
        // "Measurably above": by more than twice this file's whole error budget.
        const bool ok = newContrast > oldContrast + 2.0 * kEpsilonBytes;
        std::printf("LIGHT RIM CONTRAST vs near-white backdrop:\n  old=%7.3f new=%7.3f (need > old + %.1f) %s\n", oldContrast,
                    newContrast, 2.0 * kEpsilonBytes, ok ? "OK" : "FAIL");
        if (!ok) {
            allPassed = false;
        }
    }

    // =========================================================================
    // PASS 8: BACKDROP REFRACTION (kFrostBackdropFragmentShaderSource), the
    // pass Frost::drawWindow() draws onto the real render target over Blur's
    // output. Float input and output (RGBA32F) so a sub-pixel displacement is
    // measured exactly: the input texel (tx, ty) stores its own centre in
    // TOP-LEFT-origin backdrop pixels, (tx + 0.5, H - (ty + 0.5)), so the
    // sampled R/G IS the position the shader read. Displacement = sample -
    // own position. Expectations from the tokens: d(edgeDist) = strength *
    // edge_falloff * clamp(1 - edgeDist / edge_falloff, 0, 1), INWARD.
    // =========================================================================
    constexpr int kBackdropWidth = 64;
    constexpr int kBackdropHeight = 40;
    // Bilinear weights may be quantized by the rasteriser (8 fractional bits
    // is common): 1/256 px plus float slack. One displacement step between
    // neighbouring pixels is strength (0.035 px at the original tokens), well
    // above this.
    constexpr double kPositionEpsilon = 0.005;
    const double strength = Kuura::Tokens::kMaterialRefractionStrength;
    const double falloffPx = static_cast<double>(Kuura::Tokens::kMaterialRefractionEdgeFalloff);
    const auto expectedDisplacement = [strength, falloffPx](double edgeDist) {
        return strength * falloffPx * std::clamp(1.0 - edgeDist / falloffPx, 0.0, 1.0);
    };

    const GLuint backdropFragment = compileShader(GL_FRAGMENT_SHADER, Kuura::kFrostBackdropFragmentShaderSource);
    if (backdropFragment == 0) {
        return EXIT_FAILURE;
    }
    const GLuint backdropProgram = glCreateProgram_();
    glAttachShader_(backdropProgram, vertexShader);
    glAttachShader_(backdropProgram, backdropFragment);
    glBindAttribLocation_(backdropProgram, 0, "position");
    glBindAttribLocation_(backdropProgram, 1, "texcoord");
    glLinkProgram_(backdropProgram);
    glGetProgramiv_(backdropProgram, GL_LINK_STATUS, &linked);
    if (linked == GL_FALSE) {
        std::fprintf(stderr, "backdrop program link failed\n");
        return EXIT_FAILURE;
    }
    glUseProgram_(backdropProgram);
    glUniformMatrix4fv_(glGetUniformLocation_(backdropProgram, "modelViewProjectionMatrix"), 1, GL_FALSE, identityMvp);
    glUniform1i_(glGetUniformLocation_(backdropProgram, "sampler"), 0);
    glUniform2f_(glGetUniformLocation_(backdropProgram, "backdropSize"), static_cast<float>(kBackdropWidth), static_cast<float>(kBackdropHeight));
    glUniform1f_(glGetUniformLocation_(backdropProgram, "refractionStrength"), Kuura::Tokens::kMaterialRefractionStrength);
    glUniform1f_(glGetUniformLocation_(backdropProgram, "refractionEdgeFalloff"), static_cast<float>(Kuura::Tokens::kMaterialRefractionEdgeFalloff));

    std::vector<float> positions(static_cast<size_t>(kBackdropWidth) * kBackdropHeight * 4);
    for (int ty = 0; ty < kBackdropHeight; ++ty) {
        for (int tx = 0; tx < kBackdropWidth; ++tx) {
            const size_t offset = (static_cast<size_t>(ty) * kBackdropWidth + tx) * 4;
            positions[offset + 0] = static_cast<float>(tx) + 0.5F;
            positions[offset + 1] = static_cast<float>(kBackdropHeight) - (static_cast<float>(ty) + 0.5F);
            positions[offset + 2] = 0.0F;
            positions[offset + 3] = 1.0F;
        }
    }
    GLuint backdropTexture = 0;
    glGenTextures(1, &backdropTexture);
    glActiveTexture_(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, backdropTexture);
    // GL_LINEAR + GL_CLAMP_TO_EDGE: the copy texture's real parameters in
    // Frost::refractBackdrop().
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, kBackdropWidth, kBackdropHeight, 0, GL_RGBA, GL_FLOAT, positions.data());

    GLuint backdropOutput = 0;
    glGenTextures(1, &backdropOutput);
    glBindTexture(GL_TEXTURE_2D, backdropOutput);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, kBackdropWidth, kBackdropHeight, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    GLuint backdropFbo = 0;
    glGenFramebuffers_(1, &backdropFbo);
    glBindFramebuffer_(GL_FRAMEBUFFER, backdropFbo);
    glFramebufferTexture2D_(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, backdropOutput, 0);
    if (glCheckFramebufferStatus_(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        std::fprintf(stderr, "float framebuffer incomplete\n");
        return EXIT_FAILURE;
    }
    glViewport(0, 0, kBackdropWidth, kBackdropHeight);
    glActiveTexture_(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, backdropTexture);
    draw();

    std::vector<float> result(static_cast<size_t>(kBackdropWidth) * kBackdropHeight * 4);
    glReadPixels(0, 0, kBackdropWidth, kBackdropHeight, GL_RGBA, GL_FLOAT, result.data());
    // Displacement at top-left-origin backdrop pixel (x, y), x/y = column/row.
    const auto displacementAt = [&result](int x, int y) {
        const int glRow = kBackdropHeight - 1 - y;
        const size_t offset = (static_cast<size_t>(glRow) * kBackdropWidth + x) * 4;
        return std::pair<double, double>{result[offset + 0] - (x + 0.5), result[offset + 1] - (y + 0.5)};
    };
    const auto check = [&allPassed](const char *label, double actual, double expected, double epsilon) {
        const bool ok = std::fabs(actual - expected) <= epsilon;
        std::printf("  %-34s expected=%8.4f actual=%8.4f %s\n", label, expected, actual, ok ? "OK" : "FAIL");
        if (!ok) {
            allPassed = false;
        }
    };

    // ---- Left-edge profile along the middle row: inward is +x. Values match
    // the token formula, are monotonically non-increasing with distance, and
    // reach exactly 0 at edge_falloff. ----
    std::printf("BACKDROP LEFT-EDGE PROFILE (row %d, inward = +x):\n", kBackdropHeight / 2);
    double previous = 1.0e9;
    bool monotonic = true;
    char label[64];
    for (int x = 0; x <= static_cast<int>(falloffPx) + 2; ++x) {
        const auto [dx, dy] = displacementAt(x, kBackdropHeight / 2);
        std::snprintf(label, sizeof(label), "x=%d dx", x);
        check(label, dx, expectedDisplacement(x + 0.5), kPositionEpsilon);
        check("     dy", dy, 0.0, kPositionEpsilon);
        if (dx > previous + kPositionEpsilon) {
            monotonic = false;
        }
        previous = dx;
    }
    std::printf("  %-34s %s\n", "monotonic non-increasing", monotonic ? "OK" : "FAIL");
    if (!monotonic) {
        allPassed = false;
    }
    // The pixel at the edge is displaced by the token maximum minus half a
    // pixel of falloff -- strictly positive, so the pass is not a no-op.
    if (!(displacementAt(0, kBackdropHeight / 2).first > kPositionEpsilon)) {
        std::printf("  edge pixel not displaced: FAIL\n");
        allPassed = false;
    }

    // ---- The other three edges: inward direction (top-left origin). ----
    std::printf("BACKDROP OTHER EDGES (inward):\n");
    const double atEdge = expectedDisplacement(0.5);
    check("right edge dx (-)", displacementAt(kBackdropWidth - 1, kBackdropHeight / 2).first, -atEdge, kPositionEpsilon);
    check("top edge dy (+)", displacementAt(kBackdropWidth / 2, 0).second, atEdge, kPositionEpsilon);
    check("bottom edge dy (-)", displacementAt(kBackdropWidth / 2, kBackdropHeight - 1).second, -atEdge, kPositionEpsilon);

    // ---- Interior: every pixel at or beyond edge_falloff from all edges is
    // an exact copy (samples land on texel centres: no filtering at all). ----
    int interiorPixels = 0;
    int interiorMoved = 0;
    for (int y = 0; y < kBackdropHeight; ++y) {
        for (int x = 0; x < kBackdropWidth; ++x) {
            const double edgeDist = std::min(std::min(x + 0.5, kBackdropWidth - (x + 0.5)), std::min(y + 0.5, kBackdropHeight - (y + 0.5)));
            if (edgeDist < falloffPx) {
                continue;
            }
            ++interiorPixels;
            const auto [dx, dy] = displacementAt(x, y);
            if (std::fabs(dx) > 1.0e-4 || std::fabs(dy) > 1.0e-4) {
                ++interiorMoved;
            }
        }
    }
    std::printf("BACKDROP INTERIOR: %d pixels, %d displaced %s\n", interiorPixels, interiorMoved,
                (interiorPixels > 0 && interiorMoved == 0) ? "OK" : "FAIL");
    if (interiorPixels == 0 || interiorMoved != 0) {
        allPassed = false;
    }

    // ---- Premultiplied alpha: an alpha ramp along x with colour exactly
    // half of alpha (rgb = x*2, a = x*4 bytes: a valid premultiplied 50% grey
    // at every coverage). Refraction blends neighbouring texels; blending
    // premultiplied values keeps rgb = a/2 exactly and rgb <= a everywhere --
    // which a straight-alpha mix would not. ----
    {
        std::vector<uint8_t> ramp(static_cast<size_t>(kBackdropWidth) * kBackdropHeight * 4);
        for (int ty = 0; ty < kBackdropHeight; ++ty) {
            for (int tx = 0; tx < kBackdropWidth; ++tx) {
                const size_t offset = (static_cast<size_t>(ty) * kBackdropWidth + tx) * 4;
                ramp[offset + 0] = static_cast<uint8_t>(tx * 2);
                ramp[offset + 1] = static_cast<uint8_t>(tx * 2);
                ramp[offset + 2] = static_cast<uint8_t>(tx * 2);
                ramp[offset + 3] = static_cast<uint8_t>(tx * 4);
            }
        }
        glBindTexture(GL_TEXTURE_2D, backdropTexture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, kBackdropWidth, kBackdropHeight, 0, GL_RGBA, GL_UNSIGNED_BYTE, ramp.data());
        draw();
        glReadPixels(0, 0, kBackdropWidth, kBackdropHeight, GL_RGBA, GL_FLOAT, result.data());
        double worstRatioError = 0.0;
        bool rgbWithinAlpha = true;
        for (size_t i = 0; i < result.size(); i += 4) {
            const double a = result[i + 3];
            for (size_t channel = 0; channel < 3; ++channel) {
                worstRatioError = std::max(worstRatioError, std::fabs(result[i + channel] - 0.5 * a));
                if (result[i + channel] > a + 1.0e-5) {
                    rgbWithinAlpha = false;
                }
            }
        }
        // One byte: llvmpipe filters an 8-bit texture in 8-bit fixed point and
        // rounds each channel independently (observed: exactly 0.5/255), so rgb
        // can be off by 0.5 and a/2 by 0.25 of a byte. A colour/alpha mix-up
        // (e.g. treating the copy as straight alpha) would break rgb <= a or
        // the 1:2 ratio by far more across this 0..252 alpha ramp.
        const bool ok = rgbWithinAlpha && worstRatioError <= 1.0 / 255.0;
        std::printf("BACKDROP PREMULTIPLIED: rgb<=a %s, max |rgb - a/2| = %.6f %s\n", rgbWithinAlpha ? "yes" : "NO", worstRatioError,
                    ok ? "OK" : "FAIL");
        if (!ok) {
            allPassed = false;
        }
        // The displaced edge texel really is a blend (else this proves nothing):
        // at the left edge the sample moves inward, so alpha rises above the
        // edge texel's own 0 bytes.
        const double edgeAlpha = result[(static_cast<size_t>(kBackdropHeight / 2) * kBackdropWidth + 0) * 4 + 3];
        std::printf("  left-edge alpha after refraction %.4f (> 0 expected) %s\n", edgeAlpha, edgeAlpha > 0.0 ? "OK" : "FAIL");
        if (!(edgeAlpha > 0.0)) {
            allPassed = false;
        }
    }

    std::printf("\n%s\n", allPassed ? "ALL CHECKS PASSED" : "SOME CHECKS FAILED");
    return allPassed ? EXIT_SUCCESS : EXIT_FAILURE;
}
