"""
Command line tool that turns design/tokens.json into theme files for every target.

This file is the LOCKED INTERFACE: implement the bodies without changing the
signatures or the file layout below. Standard library only plus the modules of
this package (design.validate, design.generators.*).

Usage (from the project root):
    python -m design.generate [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory (both modes for every target, plus
five mode-independent layout/header/fontconfig files):
    plasma/<name>-light.colors   plasma/<name>-dark.colors    (generators.plasma_colors)
    kvantum/<name>-light.kvconfig kvantum/<name>-dark.kvconfig (generators.kvantum)
    gtk/<name>-light.css         gtk/<name>-dark.css          (generators.gtk_css)
    qml/Tokens-light.qml         qml/Tokens-dark.qml          (generators.qml_singleton)
    layout/plasma-org.kde.plasma.desktop-appletsrc              (generators.plasma_layout.render)
    layout/plasmashellrc                                         (generators.plasma_layout.render_view_settings)
    layout/kactivitymanagerdrc                                   (generators.plasma_layout.render_activities)
    cpp/tokens.h                                                 (generators.cpp_header.render)
    fontconfig/<name>-fonts.conf                                 (generators.fontconfig.render)

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of this
file's directory); --name = environment variable DISTRO_NAME, else "theme".
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate(tokens: dict, out_dir: Path, name: str) -> list[Path]:
    """
    Write every target file for both modes.

    Args:
        tokens: Validated token dictionary.
        out_dir: Directory that receives the plasma/, kvantum/, gtk/, qml/ trees
            (created as needed). Existing files are overwritten.
        name: Theme name passed to the generators and used in file names.

    Returns:
        The paths of all written files, sorted, always 13 entries: the 4
        mode-dependent generators below times 2 modes (light/dark), plus three
        mode-independent panel layout files (layout has no light/dark
        variant, so generators.plasma_layout's three functions are each called
        once, not per mode: render() for the appletsrc, render_view_settings()
        for the panel thickness/floating settings appletsrc cannot express, and
        render_activities() for the matching activity id - see plasma_layout's
        own module docstring for why there are three), plus ONE mode-independent
        C++ token header (generators.cpp_header.render() - colour tokens are
        mode-dependent and that generator's locked signature takes no mode
        argument at all, see its own module docstring, so like plasma_layout it
        is rendered once, not per mode), plus ONE mode-independent fontconfig
        alias file (generators.fontconfig.render(tokens, name) - also no mode
        argument, for the same reason, but DOES take name since the alias
        family itself is branded per distro; see that module's own docstring).

    Raises:
        ValueError: if name is not lowercase letters, digits, "_" or "-".
    """
    # WHY: Validate name before creating any files
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError("name must be lowercase letters, digits, '_' or '-'")

    # Import generators here to avoid circular imports
    from design.generators import cpp_header, fontconfig, gtk_css, qml_singleton, plasma_colors, kvantum, plasma_layout

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Map generator directory names to file extensions (for non-QML generators)
    # WHY: Use a dict instead of if/elif chain for clarity and maintainability
    ext_map = {
        "plasma": "colors",
        "kvantum": "kvconfig",
        "gtk": "css",
    }

    # Define the 4 mode-dependent generators: each produces 2 files (light
    # and dark). plasma_layout is deliberately NOT in this list - it has no
    # light/dark variant, so it is rendered once below instead of per mode.
    # Each generator has a name and render function
    generators = [
        ("plasma", plasma_colors),
        ("kvantum", kvantum),
        ("gtk", gtk_css),
        ("qml", qml_singleton),
    ]

    written_paths = []

    for gen_dir, gen_module in generators:
        subdir = out_dir / gen_dir
        subdir.mkdir(parents=True, exist_ok=True)

        for mode in ["light", "dark"]:
            # Render the content
            content = gen_module.render(tokens, mode=mode, name=name)

            # Determine the output filename based on generator
            if gen_dir == "qml":
                # QML uses Tokens-<mode>.qml
                filename = f"Tokens-{mode}.qml"
            else:
                # Others use <name>-<mode>.<ext>
                ext = ext_map[gen_dir]
                filename = f"{name}-{mode}.{ext}"

            file_path = subdir / filename

            # Write the file
            file_path.write_text(content, encoding="utf-8")
            written_paths.append(file_path)

    # Panel layout: mode-independent (no light/dark variant), so it is
    # rendered and written once, outside the light/dark loop above, to its
    # own "layout" subdirectory rather than one of the 4 generators' dirs.
    # THREE files, all named after their real install target (Plasma's own filenames,
    # not "<name>-..." as before) -- panel thickness/floating/centring turned out live
    # to be stored in plasmashellrc, not in appletsrc, and the desktop containment's
    # activityId needs a matching kactivitymanagerdrc or it refers to an activity
    # nothing else knows about (see plasma_layout's own module docstring, "SECOND FILE
    # DISCOVERED" / "THIRD FILE"), so all three must be generated and shipped together
    # for the panel layout to actually take effect and the desktop to stay intact.
    layout_subdir = out_dir / "layout"
    layout_subdir.mkdir(parents=True, exist_ok=True)

    appletsrc_path = layout_subdir / "plasma-org.kde.plasma.desktop-appletsrc"
    appletsrc_path.write_text(plasma_layout.render(tokens), encoding="utf-8")
    written_paths.append(appletsrc_path)

    plasmashellrc_path = layout_subdir / "plasmashellrc"
    plasmashellrc_path.write_text(plasma_layout.render_view_settings(tokens), encoding="utf-8")
    written_paths.append(plasmashellrc_path)

    kactivitymanagerdrc_path = layout_subdir / "kactivitymanagerdrc"
    kactivitymanagerdrc_path.write_text(plasma_layout.render_activities(tokens), encoding="utf-8")
    written_paths.append(kactivitymanagerdrc_path)

    # C++ token header: mode-independent (no light/dark variant, see
    # cpp_header's own module docstring), so it is rendered and written once,
    # like the three layout files above, to its own "cpp" subdirectory. This is
    # what lets packages/kuura-frost's real material shader (src/frost.cpp)
    # read design/tokens.json's material.* values as compiled constexpr C++
    # constants instead of a second, hand-copied (and driftable) set of
    # literals - see cpp_header.py's own module docstring for the full "why".
    cpp_subdir = out_dir / "cpp"
    cpp_subdir.mkdir(parents=True, exist_ok=True)

    tokens_header_path = cpp_subdir / "tokens.h"
    tokens_header_path.write_text(cpp_header.render(tokens), encoding="utf-8")
    written_paths.append(tokens_header_path)

    # Fontconfig alias: mode-independent like the two blocks above, but DOES take
    # `name` (the alias family itself is branded per distro, e.g. "Kuura Sans") -
    # see design/generators/fontconfig.py's own module docstring.
    fontconfig_subdir = out_dir / "fontconfig"
    fontconfig_subdir.mkdir(parents=True, exist_ok=True)

    fontconfig_path = fontconfig_subdir / f"{name}-fonts.conf"
    fontconfig_path.write_text(fontconfig.render(tokens, name), encoding="utf-8")
    written_paths.append(fontconfig_path)

    # Return sorted paths
    return sorted(written_paths)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Args:
        argv: Command line arguments, defaults to sys.argv[1:].

    Returns:
        0 on success; 1 when the tokens are invalid (all problems printed to
        stderr, nothing written); 2 when --out-dir would be outside
        PROJECT_ROOT or --name is invalid.
    """
    import argparse

    from design.validate import TokenError, load_tokens

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Generate theme files from design tokens")
    parser.add_argument(
        "--tokens",
        type=Path,
        default=Path(__file__).parent / "tokens.json",
        help="Path to tokens.json (default: design/tokens.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / ".build" / "generated",
        help="Output directory (default: .build/generated)",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("DISTRO_NAME", "theme"),
        help="Theme name (default: DISTRO_NAME env var or 'theme')",
    )

    args = parser.parse_args(argv)

    # Validate name
    if not re.fullmatch(r"[a-z0-9_-]+", args.name):
        print(f"error: name must be lowercase letters, digits, '_' or '-', got {args.name!r}", file=sys.stderr)
        return 2

    # Validate out_dir is within PROJECT_ROOT using strict path component check
    try:
        out_dir_resolved = args.out_dir.resolve()
        project_root_resolved = PROJECT_ROOT.resolve()
        # WHY: Use parents check instead of string prefix to prevent sibling directory attacks
        # (e.g., /proj and /proj_evil would both match with startswith, but not with parents check)
        if out_dir_resolved != project_root_resolved and project_root_resolved not in out_dir_resolved.parents:
            print("error: --out-dir must stay inside the project directory", file=sys.stderr)
            return 2
    except (ValueError, RuntimeError):
        print("error: invalid out-dir path", file=sys.stderr)
        return 2

    # Load and validate tokens
    try:
        tokens = load_tokens(args.tokens)
    except TokenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Generate files
    try:
        generate(tokens, args.out_dir, args.name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
