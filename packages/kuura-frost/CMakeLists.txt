# Frost: the KWin compositor effect that renders the project's glass "material"
# (background blur + edge refraction + specular edge highlight + anti-banding
# noise) for the desktop shell's own translucent surfaces (Vaihe 4 of the working
# brief, docs/SHELL_CONTRACT.md's "material" tokens that Vaihe 3 found no stock
# KWin/Plasma lever for).
#
# THIS FILE IS A BUILD-TOOLCHAIN SKELETON, NOT THE FINISHED EFFECT. It exists so
# the real compiler/clang-tidy pipeline (scripts/run_static_analysis.ps1) has a
# genuine, buildable target to verify against before the shader/effect logic
# itself is written. src/frost.h documents the locked class contract; src/frost.cpp
# is currently a placeholder implementation, not the real material.
#
# find_package(KWin) works directly because the pinned Arch snapshot's kwin
# package ships its own CMake package config (/usr/lib/cmake/KWin/*.cmake) --
# confirmed live against the exact pinned archive snapshot, not assumed; see the
# V4 investigation notes handed back with this change for the full evidence
# trail (headers, CMake config paths, KWin GitLab source citations).
cmake_minimum_required(VERSION 3.16)
project(kuura-frost)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# WHY: main.cpp's `#include "main.moc"` (the real, confirmed KWin plugin-factory
# pattern, see main.cpp's own header comment) needs Qt's Meta-Object Compiler to
# actually run and generate that file; AUTOMOC is what makes CMake invoke moc
# automatically for any translation unit with a Q_OBJECT-bearing include or a
# *.moc include. Missing this produced a real, confirmed build failure
# ("main.moc: No such file or directory") before it was added.
set(CMAKE_AUTOMOC ON)
# WHY exported compile commands: this is what lets clang-tidy (and any other
# tool that consumes compile_commands.json) see the exact include paths and
# defines each translation unit actually built with, instead of guessing them.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# A minimum version is required, not just NO_MODULE: KDECMakeSettings.cmake
# (included below) only sets CMAKE_LIBRARY_OUTPUT_DIRECTORY when
# ECM_GLOBAL_FIND_VERSION compares >= 5.38.0, and that variable is only
# populated when find_package() is given an actual version to look for --
# confirmed by a real build attempt failing with "CMAKE_LIBRARY_OUTPUT_DIRECTORY
# is not set" until this version was added, even with KDECMakeSettings already
# included. 6.0.0 is a safe floor well under the pinned snapshot's real
# extra-cmake-modules 6.30.0-1.
find_package(ECM 6.0.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

# WHY both of these, confirmed by a real build attempt, not assumed in advance:
# kcoreaddons_add_plugin()'s own real definition
# (/usr/lib/cmake/KF6CoreAddons/KF6CoreAddonsMacros.cmake at the pinned snapshot,
# fetched and read in full) does `if (NOT BUILD_SHARED_LIBS) set(ARGS_STATIC ON)`
# -- CMake's own BUILD_SHARED_LIBS defaults to OFF when never set, which silently
# produced a STATIC .a archive (confirmed: build succeeded but linked
# "libkuura_frost.a", not a loadable module) instead of the real, loadable
# .so a KWin out-of-tree effect plugin must be. Setting it ON here is what makes
# the macro's own `else()` branch (`add_library(... MODULE ...)`) run instead.
# The same macro's MODULE branch also requires CMAKE_LIBRARY_OUTPUT_DIRECTORY to
# already be set or it hard-errors ("set it explicitly or include
# KDECMakeSettings") -- ECM's own KDECMakeSettings module (found alongside the
# macro file under /usr/share/ECM/kde-modules/) is the real, standard way KDE's
# own build system supplies it, reused here rather than hand-rolling an
# equivalent value. KDECMakeSettings itself then hard-errors ("Neither
# KDE_INSTALL_LIBDIR nor LIB_INSTALL_DIR is set", confirmed by a real build
# attempt) unless KDEInstallDirs was included first -- the standard KDE/ECM
# three-module include order, not something specific to this project.
set(BUILD_SHARED_LIBS ON)
include(KDEInstallDirs)
include(KDECMakeSettings)

# Widgets is required even though this effect draws nothing with it directly:
# KWin::kwin's own exported CMake target links Qt6::Widgets, confirmed by a
# real build attempt (KWinTargets.cmake failed with "the target was not
# found" until this component was added) -- not assumed in advance.
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)
find_package(KF6CoreAddons REQUIRED)
find_package(KWin REQUIRED)
# WHY: frost.cpp reads a window's decoration blur region the same way
# BlurEffect does (window->decoration()->blurRegion(), confirmed at blur.cpp),
# which needs <KDecoration3/Decoration>. That header is real and installed
# (/usr/include/KDecoration3/KDecoration3/Decoration -- the doubled path
# segment is KDecoration3's own layout, not a mistake) but is NOT reachable
# through KWin::kwin's own include paths -- confirmed by a real build failure
# ("KDecoration3/Decoration: No such file or directory") before this was
# added. find_package(KDecoration3) is what supplies the right -isystem
# include path via its own exported target below.
find_package(KDecoration3 REQUIRED)

kcoreaddons_add_plugin(kuura_frost
    SOURCES src/frost.cpp src/main.cpp
    INSTALL_NAMESPACE "kwin/effects/plugins"
)

target_link_libraries(kuura_frost PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    KF6::CoreAddons
    KWin::kwin
    KDecoration3::KDecoration
)

target_include_directories(kuura_frost PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
