// Plugin factory registration. Macro usage confirmed against KWin's own real
// src/plugins/blur/main.cpp at the pinned tag (v6.7.5, commit
// ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7), fetched live from
// https://invent.kde.org/plasma/kwin/-/raw/v6.7.5/src/plugins/blur/main.cpp --
// not guessed from a recalled/older KWin plugin convention. Blur's own call is
// wrapped in `namespace KWin { ... }` only because BlurEffect itself is an
// in-tree, KWin-namespaced builtin effect; Frost is an out-of-tree plugin in
// its own Kuura namespace, so the class name is fully qualified instead and no
// extra namespace wrapper is used here.
//
// ASSUMPTION, not yet build-verified: blur's own metadata file is
// "metadata.json.stripped", a build-processed artifact specific to KWin's
// in-tree CMake macros for builtin effects (kwin_add_builtin_effect). This
// plugin instead ships its raw metadata.json directly via kcoreaddons_add_plugin
// (the confirmed out-of-tree registration path, see CMakeLists.txt), which
// does not use that stripping step -- if the real build shows this filename
// needs to differ, that is expected to surface as a build/runtime error to fix,
// not something guessed correctly on the first try.

#include "frost.h"

#include <effect/effect.h>

KWIN_EFFECT_FACTORY_SUPPORTED_ENABLED(Kuura::Frost,
                                       "metadata.json",
                                       return Kuura::Frost::supported();
                                       ,
                                       return true;)

#include "main.moc"
