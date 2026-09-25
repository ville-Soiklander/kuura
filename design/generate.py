"""
Command line tool that turns design/tokens.json into theme files for every target.

This file is the LOCKED INTERFACE: implement the bodies without changing the
signatures or the file layout below. Standard library only plus the modules of
this package (design.validate, design.generators.*).

Usage (from the project root):
    python -m design.generate [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory (both modes for every target):
    plasma/<name>-light.colors   plasma/<name>-dark.colors    (generators.plasma_colors)
    kvantum/<name>-light.kvconfig kvantum/<name>-dark.kvconfig (generators.kvantum)
    gtk/<name>-light.css         gtk/<name>-dark.css          (generators.gtk_css)
    qml/Tokens-light.qml         qml/Tokens-dark.qml          (generators.qml_singleton)

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
        The paths of all written files, sorted, always 8 entries.

    Raises:
        ValueError: if name is not lowercase letters, digits, "_" or "-".
    """
    # WHY: Validate name before creating any files
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError("name must be lowercase letters, digits, '_' or '-'")

    # Import generators here to avoid circular imports
    from design.generators import gtk_css, qml_singleton, plasma_colors, kvantum

    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)

    # Map generator directory names to file extensions (for non-QML generators)
    # WHY: Use a dict instead of if/elif chain for clarity and maintainability
    ext_map = {
        "plasma": "colors",
        "kvantum": "kvconfig",
        "gtk": "css",
    }

    # Define the 4 generators: each produces 2 files (light and dark)
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
