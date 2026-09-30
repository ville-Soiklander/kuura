"""
Command line tool that turns design/tokens.json into Firefox's own
userChrome.css/userContent.css (Vaihe 6, the Firefox sub-task of "Sovellustason
viimeistely").

This file mirrors design/generate.py's own conventions closely (argparse flags,
the path-traversal guard, return codes) so this CLI behaves the same way to
anyone who already knows it; it is a separate entry point rather than a new
mode of design/generate.py for the same reason design/generate_icons.py already
is one: Firefox output is not part of design/generate.py's own fixed, already-
locked file-count contract (that module's own docstring/tests enumerate an
exact manifest), and Firefox needs neither the light/dark-per-file split every
one of design/generate.py's four mode-dependent generators uses (both palettes
land in ONE file per Firefox output, see design/generators/firefox_theme.py's
own module docstring) nor that module's mode-independent generators at all.

Usage (from the project root):
    python -m design.generate_firefox [--tokens FILE] [--out-dir DIR] [--name NAME]

Output layout under the output directory:
    firefox/chrome/userChrome.css    (generators.firefox_theme.render_chrome)
    firefox/chrome/userContent.css   (generators.firefox_theme.render_content)
Both files live directly under a "chrome" subdirectory because that is Firefox's
own required, real path inside a profile (<profile>/chrome/userChrome.css,
<profile>/chrome/userContent.css) - not a naming choice made by this project.

`--name` is accepted for CLI symmetry with design/generate.py and
design/generate_icons.py, but - like generate_icons.py's own icon output - is
currently unused by the Firefox generator itself: no visible "kuura" branding
belongs in browser chrome (see firefox_theme.py's own module docstring), so
render_chrome()/render_content() never read it beyond accepting it for
signature parity with every other generator's (tokens, mode, name) shape.

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of this
file's directory, same default design/generate.py and design/generate_icons.py
use); --name = environment variable DISTRO_NAME, else "theme".
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Generated files must stay inside the project tree (path traversal guard),
# mirroring design/generate.py's and design/generate_icons.py's own PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_firefox(tokens: dict, out_dir: Path, name: str) -> list[Path]:
    """
    Render and write userChrome.css and userContent.css.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        out_dir: Directory that receives the firefox/chrome/ subdirectory
            (created as needed). Existing files are overwritten.
        name: Theme name, passed through to the generator for signature parity
            only (see module docstring - currently not read by the CSS itself).

    Returns:
        The paths of both written files, sorted: firefox/chrome/userChrome.css
        and firefox/chrome/userContent.css.
    """
    # Imported here, not at module scope, mirroring design/generate.py's and
    # design/generate_icons.py's own "import generators late" convention.
    from design.generators import firefox_theme

    chrome_subdir = out_dir / "firefox" / "chrome"
    chrome_subdir.mkdir(parents=True, exist_ok=True)

    written_paths = []

    # mode is passed as "light" only for signature parity with every other
    # generator's (tokens, mode, name) shape - both render_chrome() and
    # render_content() ignore its value and always emit BOTH palettes in one
    # file (see firefox_theme.py's own module docstring for why), so there is
    # no second, "dark" call here the way design/generate.py's four
    # mode-dependent generators each need one.
    user_chrome_path = chrome_subdir / "userChrome.css"
    user_chrome_path.write_text(
        firefox_theme.render_chrome(tokens, mode="light", name=name), encoding="utf-8"
    )
    written_paths.append(user_chrome_path)

    user_content_path = chrome_subdir / "userContent.css"
    user_content_path.write_text(
        firefox_theme.render_content(tokens, mode="light", name=name), encoding="utf-8"
    )
    written_paths.append(user_content_path)

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

    parser = argparse.ArgumentParser(description="Generate Firefox userChrome.css/userContent.css from design tokens")
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
    # design/generate_icons.py, even though this generator does not itself use
    # the name (see module docstring) - a caller that scripts all three CLIs
    # the same way should see the same rejection.
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
    generate_firefox(tokens, args.out_dir, args.name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
