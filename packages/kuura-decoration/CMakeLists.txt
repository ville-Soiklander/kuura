# Window decoration plugin: round traffic-light buttons on the left, a title bar
# coloured from the active colour scheme, its own drop shadow and rounded corners on all
# four corners (KDecoration3::Decoration::setBorderRadius(), which only a C++ plugin can
# call). The design and the API facts behind every choice here are in INTERFACE_NOTES.md.
#
# Layout:
#   kuura_decoration_logic  static, Qt-free layout/palette/shadow logic (src/*_logic,
#                           src/geometry) - linked into the plugin AND the unit tests
#   kuura_decoration        the loadable KDecoration3 plugin module
#   tests/*_test            plain C++20 executables registered with ctest
cmake_minimum_required(VERSION 3.16)
project(kuura-decoration LANGUAGES CXX)

# C++20: <KDecoration3/Decoration> itself uses a defaulted operator<=> (BorderRadius).
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Q_OBJECT classes and plugin.cpp's `#include "plugin.moc"` need moc.
set(CMAKE_AUTOMOC ON)
# compile_commands.json for clang-tidy (scripts/run_static_analysis.ps1).
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# A version is required, not just NO_MODULE: KDECMakeSettings only sets
# CMAKE_LIBRARY_OUTPUT_DIRECTORY when ECM_GLOBAL_FIND_VERSION is >= 5.38.0, and that
# variable is only populated when find_package() is given a version (same finding as
# packages/kuura-frost/CMakeLists.txt).
find_package(ECM 6.0.0 REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})
# Standard KDE order: KDEInstallDirs first (KDECMakeSettings needs KDE_INSTALL_LIBDIR).
# KDECMakeSettings sets CMAKE_SHARED_MODULE_PREFIX to "" and enables BUILD_TESTING.
include(KDEInstallDirs)
include(KDECMakeSettings)

find_package(Qt6 REQUIRED COMPONENTS Core Gui)
find_package(KF6CoreAddons REQUIRED)  # KPluginFactory / K_PLUGIN_FACTORY_WITH_JSON
find_package(KDecoration3 REQUIRED)   # KDecoration3::KDecoration, KDECORATION_PLUGIN_DIR

# KDECORATION_PLUGIN_DIR comes from the installed KDecoration3Config.cmake. Without it the
# plugin would be installed where KWin never looks, so fail instead of guessing.
if(NOT KDECORATION_PLUGIN_DIR)
    message(FATAL_ERROR "KDECORATION_PLUGIN_DIR was not set by KDecoration3Config.cmake")
endif()

# Product name from the environment, passed by the PKGBUILD as -DDISTRO_NAME=... It ends
# up in a file name and in the plugin id, so it is validated like build_repo.sh does.
set(DISTRO_NAME "" CACHE STRING "Product name (DISTRO_NAME in .env.example)")
if(NOT DISTRO_NAME MATCHES "^[a-z0-9][a-z0-9_-]*$")
    message(FATAL_ERROR "DISTRO_NAME must be set and may only contain lowercase letters, digits, '_' and '-'")
endif()
set(KUURA_DECORATION_PLUGIN_ID "${DISTRO_NAME}.decoration")
# Display name: the product name title-cased (first letter upper case), like the QML theme
# generator did, so the product name is never hard-coded here.
string(SUBSTRING "${DISTRO_NAME}" 0 1 _deco_first)
string(SUBSTRING "${DISTRO_NAME}" 1 -1 _deco_rest)
string(TOUPPER "${_deco_first}" _deco_first)
set(KUURA_DECORATION_DISPLAY_NAME "${_deco_first}${_deco_rest} Round Buttons")
configure_file(src/metadata.json.in "${CMAKE_CURRENT_BINARY_DIR}/metadata.json" @ONLY)

# <tokens.h> and <token_colors.h>, written by the PKGBUILD's design.generate step before
# configuring. A missing directory makes the logic sources fail to compile, which is the
# intended loud failure (no token value is ever hand-copied into this package).
set(KUURA_DECORATION_GENERATED_DIR "${CMAKE_CURRENT_SOURCE_DIR}/generated/cpp")

# Pure logic. PIC because it is linked into a MODULE; the generated include dir is PUBLIC
# because the unit tests include <tokens.h> / <token_colors.h> directly.
add_library(kuura_decoration_logic STATIC
    src/geometry.cpp
    src/palette_logic.cpp
    src/shadow_logic.cpp
)
set_target_properties(kuura_decoration_logic PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(kuura_decoration_logic PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${KUURA_DECORATION_GENERATED_DIR}"
)

# WHY add_library(MODULE) and not kcoreaddons_add_plugin(): the macro silently builds a
# STATIC archive unless BUILD_SHARED_LIBS is ON (documented in kuura-frost's
# CMakeLists.txt); a plain MODULE target, as Breeze uses, has no such trap and lets the
# output name carry the plugin id directly.
add_library(kuura_decoration MODULE
    src/decoration.cpp
    src/button.cpp
    src/plugin.cpp
)
set_target_properties(kuura_decoration PROPERTIES
    OUTPUT_NAME "${KUURA_DECORATION_PLUGIN_ID}"
    PREFIX ""
)
# moc resolves the "metadata.json" named in K_PLUGIN_FACTORY_WITH_JSON via the include path.
target_include_directories(kuura_decoration PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(kuura_decoration PRIVATE
    kuura_decoration_logic
    Qt6::Core
    Qt6::Gui
    KF6::CoreAddons
    KDecoration3::KDecoration
)
install(TARGETS kuura_decoration
        DESTINATION "${KDE_INSTALL_PLUGINDIR}/${KDECORATION_PLUGIN_DIR}")

# Unit tests of the pure logic: plain C++20, int main(), non-zero exit on failure. They
# need no display, no Qt and no KDecoration3, so they run in the package build container.
if(BUILD_TESTING)
    enable_testing()
    foreach(_deco_test geometry_test palette_logic_test shadow_logic_test)
        add_executable(${_deco_test} tests/${_deco_test}.cpp)
        target_link_libraries(${_deco_test} PRIVATE kuura_decoration_logic)
        add_test(NAME ${_deco_test} COMMAND ${_deco_test})
    endforeach()
endif()
