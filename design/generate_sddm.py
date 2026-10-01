"""
Command line tool that turns design/tokens.json into the SDDM login screen
theme's `Main.qml`/`theme.conf` (Vaihe 6, the SDDM sub-task of "Sovellustason
viimeistely").

This file mirrors design/generate_firefox.py's own conventions closely
(argparse flags, the path-traversal guard, return codes) for the same reason
that file already gives: SDDM output is not part of design/generate.py's own
fixed, already-locked file-count contract, and - like Firefox - needs neither
the light/dark-per-file split every one of design/generate.py's four
mode-dependent generators uses, nor that module's mode-independent generators
at all.

WHY the greeter is pinned to "dark", not both modes in one file the way
Firefox's userChrome.css is: a login screen cannot react to the desktop
session's own light/dark toggle at all (the greeter runs before any user
session, and therefore before that preference even exists - there is no
`prefers-color-scheme`-equivalent signal SDDM's QML engine exposes). Exactly
one palette must therefore be chosen and baked in at generation time. This
project's own dark palette is picked as that one fixed mode: it matches how
most desktop login screens present (a dark, high-contrast surface regardless
of the session's own eventual theme) and gives the strongest contrast against
an unknown/unthemed environment before any user preference is known. This is
a real product/design call, not a technical requirement discovered by
research - see this change's own handback/report for the explicit flag.

Usage (from the project root):
    python -m design.generate_sddm [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory:
    sddm/Main.qml       (generators.sddm_theme.render_main_qml, mode="dark")
    sddm/theme.conf     (generators.sddm_theme.render_theme_conf, mode="dark")

`--name` is accepted for CLI symmetry with design/generate.py and
design/generate_firefox.py, but - like generate_firefox.py's own Firefox
output - is currently unused by the SDDM generator itself (see
generators/sddm_theme.py's own module docstring: no visible branding/logo,
matching Breeze's own shipped default of a hidden logo).

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of
this file's directory, same default design/generate.py and
design/generate_firefox.py use); --name = environment variable DISTRO_NAME,
else "theme".
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard),
# mirroring design/generate.py's and design/generate_firefox.py's own
# PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The one fixed mode a login screen is rendered in - see module docstring.
_GREETER_MODE = "dark"


def generate_sddm(tokens: dict, out_dir: Path, name: str) -> list[Path]:
    """
    Render and write Main.qml and theme.conf.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        out_dir: Directory that receives the sddm/ subdirectory (created as
            needed). Existing files are overwritten.
        name: Theme name, passed through to the generator for signature
            parity only (see generators/sddm_theme.py's own module docstring
            - currently not read by the greeter itself).

    Returns:
        The paths of both written files, sorted: sddm/Main.qml and
        sddm/theme.conf.
    """
    # Imported here, not at module scope, mirroring design/generate.py's and
    # design/generate_firefox.py's own "import generators late" convention.
    from design.generators import sddm_theme

    sddm_subdir = out_dir / "sddm"
    sddm_subdir.mkdir(parents=True, exist_ok=True)

    written_paths = []

    main_qml_path = sddm_subdir / "Main.qml"
    main_qml_path.write_text(
        sddm_theme.render_main_qml(tokens, mode=_GREETER_MODE, name=name), encoding="utf-8"
    )
    written_paths.append(main_qml_path)

    theme_conf_path = sddm_subdir / "theme.conf"
    theme_conf_path.write_text(
        sddm_theme.render_theme_conf(tokens, mode=_GREETER_MODE, name=name), encoding="utf-8"
    )
    written_paths.append(theme_conf_path)

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

    parser = argparse.ArgumentParser(description="Generate the SDDM greeter theme (Main.qml/theme.conf) from design tokens")
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

    # Validate name, same rule and message as design/generate.py and
    # design/generate_firefox.py, even though this generator does not itself
    # use the name (see module docstring) - a caller that scripts all three
    # CLIs the same way should see the same rejection.
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
    generate_sddm(tokens, args.out_dir, args.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
