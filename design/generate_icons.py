"""
Command line tool that turns design/tokens.json + design/icons/glyphs.py into one
SVG file per icon (Vaihe 5, "Omat assetit").

This file mirrors design/generate.py's own conventions closely (argparse flags,
the path-traversal guard, return codes) so the two CLIs behave the same way to
anyone who already knows one of them; it is a separate entry point rather than a
new mode of design/generate.py because icons are not part of that CLI's fixed,
already-locked 12-file output contract (design/generate.py's own module
docstring/tests enumerate exactly 12 files - adding a 13th-and-up, variable-count
output there would break that contract for no benefit, since icons need none of
the light/dark or `--name` machinery the other 4 mode-dependent generators do).

Usage (from the project root):
    python -m design.generate_icons [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory:
    icons/<icon_id>.svg   one file per key of design.icons.glyphs.ICONS
        (generators.icon_svg.render_icon)

`--name` is accepted for CLI symmetry with design/generate.py (and to leave room
for a future per-theme icon naming scheme) but is currently unused by this
generator: icon output does not vary by theme name, since icon_svg.render_icon()
takes no `name` argument at all (only `tokens` and a glyph's own content - see
its own module docstring for why the icon frame is independent of everything a
theme name would otherwise influence).

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of this
file's directory, same default design/generate.py uses) --name = environment
variable DISTRO_NAME, else "theme".
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard),
# mirroring design/generate.py's own PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_icons(tokens: dict, out_dir: Path) -> list[Path]:
    """
    Render and write every icon listed in design.icons.glyphs.ICONS.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        out_dir: Directory that receives the icons/ subdirectory (created as
            needed). Existing files are overwritten.

    Returns:
        The paths of all written files, sorted - one per design.icons.glyphs.ICONS
        entry.
    """
    # Imported here, not at module scope, to mirror design/generate.py's own
    # "import generators late" convention (keeps a bare `import design.generate_icons`
    # cheap and avoids import-order surprises if a generator ever imports this
    # module back for testing).
    from design.generators import icon_svg
    from design.icons.glyphs import ICONS

    icons_subdir = out_dir / "icons"
    icons_subdir.mkdir(parents=True, exist_ok=True)

    written_paths = []
    for icon_id, glyph_content in ICONS.items():
        content = icon_svg.render_icon(tokens, glyph_content)
        file_path = icons_subdir / f"{icon_id}.svg"
        file_path.write_text(content, encoding="utf-8")
        written_paths.append(file_path)

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

    parser = argparse.ArgumentParser(description="Generate icon SVGs from design tokens")
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
        help="Theme name (default: DISTRO_NAME env var or 'theme'; accepted for "
        "CLI symmetry with design/generate.py, currently unused - see module docstring)",
    )

    args = parser.parse_args(argv)

    # Validate name, same rule and message as design/generate.py, even though
    # this generator does not itself use the name (see module docstring) - a
    # caller that scripts both CLIs the same way should see the same rejection.
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
    generate_icons(tokens, args.out_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
