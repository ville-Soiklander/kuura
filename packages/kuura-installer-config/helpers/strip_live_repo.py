#!/usr/bin/python3
"""
Remove one repository section from a pacman.conf.

WHY: the live ISO carries a local signed repository (file:///srv/repo) with a
matching pacman.conf section so the live session can install from local media.
Calamares' unpackfs copies that pacman.conf onto the target; an installed system has
no such media, so the section would make every `pacman -Syu` fail. The installer's
shellprocess step calls this helper to drop exactly that section and nothing else.

Usage: strip-live-repo <section-name> [pacman.conf path]
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_CONF = "/etc/pacman.conf"

# Repository names pacman accepts are plain tokens; refusing anything else keeps the
# helper from being steered at another section by a malformed argument.
_NAME_RE = re.compile(r"[A-Za-z0-9._+-]+")

# A section header is a whole line "[name]" (whitespace tolerated). A commented-out
# header starts with '#' and therefore never matches.
_HEADER_RE = re.compile(r"^\s*\[([^\]]*)\]\s*$")


def _is_header(line: str) -> bool:
    """Return True if the line is a (non-commented) section header."""
    return _HEADER_RE.match(line) is not None


def _is_filler(line: str) -> bool:
    """Return True for blank and comment-only lines."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def remove_section(text: str, name: str) -> str:
    """
    Return pacman.conf text with the section ``[name]`` removed.

    The header and its option lines (including comments between them) are dropped.
    Trailing blank/comment lines before the next header are kept, because by pacman.conf
    convention they introduce the following section. Absent section: text is returned
    unchanged, so the operation is idempotent.

    Args:
        text: Full pacman.conf contents.
        name: Section name, e.g. the distro's repository name.

    Returns:
        The edited text.

    Raises:
        ValueError: name is empty, malformed, or "options" (global settings).
    """
    if not _NAME_RE.fullmatch(name) or name == "options":
        raise ValueError("invalid section name")

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _HEADER_RE.match(lines[i])
        if not (match and match.group(1) == name):
            out.append(lines[i])
            i += 1
            continue
        # Body = everything up to the next header.
        j = i + 1
        while j < len(lines) and not _is_header(lines[j]):
            j += 1
        body = lines[i + 1 : j]
        # Keep the trailing filler run (it belongs to the next section's intro).
        keep_from = len(body)
        while keep_from > 0 and _is_filler(body[keep_from - 1]):
            keep_from -= 1
        out.extend(body[keep_from:])
        i = j
    return "".join(out)


def main(argv: list[str]) -> int:
    """
    Edit a pacman.conf in place, atomically.

    Args:
        argv: ``[section-name]`` or ``[section-name, conf-path]``.

    Returns:
        0 on success (including "section absent"), 1 on any failure. Messages are
        generic on purpose: no paths, no tracebacks.
    """
    if len(argv) not in (1, 2):
        print("usage: strip-live-repo <section-name> [pacman.conf]", file=sys.stderr)
        return 1
    conf = Path(argv[1] if len(argv) == 2 else DEFAULT_CONF)
    tmp_name = None
    try:
        original = conf.read_bytes().decode("utf-8")
        edited = remove_section(original, argv[0])
        if edited == original:
            return 0
        # Write a sibling temp file then rename, so an interrupted run can never leave
        # a truncated pacman.conf on the target.
        fd, tmp_name = tempfile.mkstemp(dir=conf.parent, prefix=".pacman.conf.")
        with os.fdopen(fd, "wb") as handle:
            handle.write(edited.encode("utf-8"))
        os.chmod(tmp_name, conf.stat().st_mode & 0o7777)
        os.replace(tmp_name, conf)
        tmp_name = None
    except (OSError, ValueError, UnicodeError):
        print("could not update the package manager configuration", file=sys.stderr)
        return 1
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
