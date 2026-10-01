"""
Command line tool that turns design/tokens.json into the Plasma "Look and
Feel" package's logout/shutdown confirmation dialog (Vaihe 6, the shutdown-
dialog sub-task of "Sovellustason viimeistely").

This file mirrors design/generate_sddm.py's own conventions closely
(argparse flags, the path-traversal guard, return codes, `python -m
design.generate_lookandfeel` invocation) for the same reason that file
already gives relative to design/generate.py: this output is not part of
design/generate.py's own fixed, already-locked file-count contract, and -
like the SDDM greeter - needs neither the light/dark-per-file split every
one of design/generate.py's four mode-dependent generators uses, nor that
module's mode-independent generators at all.

WHY the dialog is pinned to "dark", not both modes in one file: see
design/generators/lookandfeel_theme.py's own module docstring - a Look-and-
Feel logout dialog's QML has no real, confirmed live dark-mode-switch hook
(no theme.conf-like runtime override surface, no documented
prefers-color-scheme equivalent), so exactly one palette must be chosen and
baked in at generation time, the same way design/generate_sddm.py already
must for the greeter. "dark" is picked for this dialog for the same real
product reason design/generate_sddm.py's own module docstring gives for the
greeter's own fixed choice: this is a short-lived, high-stakes confirmation
surface (like a login screen, unlike an ordinary in-session window), and a
fixed, deliberately high-contrast appearance reads more consistent across
every boot than whichever light/dark mode a given session happens to be in
at the moment it is shown - matching this project's own SDDM greeter choice
keeps every "outside/edge of a normal session" surface visually consistent
with each other. This is a real product/design call, not a technical
requirement discovered by research - see this change's own handback/report
for the explicit flag.

Usage (from the project root):
    python -m design.generate_lookandfeel [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory (mirroring the real, fixed
Plasma/LookAndFeel KPackage layout 1:1, so packages/kuura-lookandfeel/'s own
PKGBUILD can install every file unmodified):
    lookandfeel/metadata.json                  (generators.lookandfeel_theme.render_metadata_json)
    lookandfeel/contents/logout/Logout.qml      (generators.lookandfeel_theme.render_logout_qml, mode="dark")

`--name` is accepted for CLI symmetry with design/generate.py and
design/generate_sddm.py. Unlike SDDM's own generator (where `name` is fully
unused), render_metadata_json() DOES read it - for the human-readable
KPlugin.Name/Description fields only, never for KPlugin.Id, which is a fixed
literal ("kuura") regardless of `--name` - see
design/generators/lookandfeel_theme.py's own module docstring, point 5, for
why that one value must stay pinned to match the already-shipped
kdeglobals' LookAndFeelPackage key.

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of
this file's directory, same default design/generate.py and
design/generate_sddm.py use); --name = environment variable DISTRO_NAME,
else "theme".
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard),
# mirroring design/generate.py's and design/generate_sddm.py's own PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The one fixed mode this dialog is rendered in - see module docstring.
_DIALOG_MODE = "dark"


def generate_lookandfeel(tokens: dict, out_dir: Path, name: str) -> list[Path]:
    """
    Render and write metadata.json and contents/logout/Logout.qml.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        out_dir: Directory that receives the lookandfeel/ subdirectory
            (created as needed, including its own contents/logout/
            subdirectory). Existing files are overwritten.
        name: Theme name, passed through to the generator - read only for
            metadata.json's own human-readable KPlugin.Name/Description
            fields (see generators/lookandfeel_theme.py's own module
            docstring - KPlugin.Id itself stays a fixed literal regardless
            of this argument).

    Returns:
        The paths of both written files, sorted: lookandfeel/
        contents/logout/Logout.qml and lookandfeel/metadata.json.
    """
    # Imported here, not at module scope, mirroring design/generate.py's and
    # design/generate_sddm.py's own "import generators late" convention.
    from design.generators import lookandfeel_theme

    lookandfeel_subdir = out_dir / "lookandfeel"
    logout_subdir = lookandfeel_subdir / "contents" / "logout"
    logout_subdir.mkdir(parents=True, exist_ok=True)

    written_paths = []

    metadata_path = lookandfeel_subdir / "metadata.json"
    metadata_path.write_text(
        lookandfeel_theme.render_metadata_json(name=name), encoding="utf-8"
    )
    written_paths.append(metadata_path)

    logout_qml_path = logout_subdir / "Logout.qml"
    logout_qml_path.write_text(
        lookandfeel_theme.render_logout_qml(tokens, mode=_DIALOG_MODE, name=name),
        encoding="utf-8",
    )
    written_paths.append(logout_qml_path)

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

    parser = argparse.ArgumentParser(
        description="Generate the Look-and-Feel logout dialog (metadata.json/Logout.qml) from design tokens"
    )
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
        help="Theme name (default: DISTRO_NAME env var or 'theme'; feeds "
        "metadata.json's own KPlugin.Name/Description only - see module docstring)",
    )

    args = parser.parse_args(argv)

    # Validate name, same rule and message as design/generate.py and
    # design/generate_sddm.py, even though KPlugin.Id itself never follows
    # this value (see module docstring) - a caller that scripts every
    # generate_*.py CLI the same way should see the same rejection.
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
    generate_lookandfeel(tokens, args.out_dir, args.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
