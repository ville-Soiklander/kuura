"""
Test-only configuration that is MERGED into the product's own user config files.

LOCKED INTERFACE (2026-10-17). Implementation and tests are delegated; the signatures,
data model and rules below are the contract.

Why this module exists: the screenshot harness image (harness/vm/Containerfile) installs
the real product and then copies ``harness/vm/guest/skel/`` over ``/etc/skel/``. Two of
those files, ``.config/kdeglobals`` and ``.config/kscreenlockerrc``, also ship in the
product (packages/kuura-shell/skel/), so the copy REPLACED the product's versions: the
harness never saw ``widgetStyle=kvantum``, ``LookAndFeelPackage=kuura`` or the lock-screen
wallpaper, and every golden showed Breeze instead of the product's Kvantum style. A real
install (harness/install) showed the opposite. Files the product also ships must
therefore never be copied wholesale; their test-only keys live as INI fragments under
``harness/vm/guest/skel-merge/`` (same relative paths as in a home directory) and are
written key by key on top of whatever the product installed.

Both harnesses apply the same fragments the same way, with ``kwriteconfig6`` (KConfig's
own writer, present wherever Plasma is), so KConfig's own group/escaping rules apply and
nothing here has to reimplement INI writing:
- harness/vm/build_rootfs.sh renders a shell script with :func:`render_shell_script`
  (home ``/etc/skel``) that the Containerfile runs after the product is installed and
  ``guest/skel/`` has been copied;
- harness/install/wizard.py runs :func:`kwriteconfig_argv` for each entry through the
  guest agent, as the desktop user, on the freshly installed target before SDDM login.

Fragment format (a deliberately small subset of KConfig INI):
- ``[Group]`` header lines; nested groups as consecutive brackets ``[A][B][C]`` (KConfig's
  own notation) -> ``groups=("A", "B", "C")``.
- ``key=value`` lines; whitespace around ``key`` and around ``=`` is stripped, the value is
  kept exactly as written after the first ``=`` (minus surrounding whitespace). Values may
  contain ``=``.
- Blank lines and lines starting with ``#`` or ``;`` are ignored.
- Anything else (a key line before any header, a header that is not a sequence of
  ``[...]``, an empty group or key name, a key with a locale suffix like ``Name[fi]``,
  a ``$`` KConfig expansion flag) is an error, so a typo fails the build instead of being
  silently dropped.
- Entries keep file order; the same file/groups/key appearing twice is an error.

Standard library only; imports on any OS (the pure functions are unit-tested on Windows).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

#: A group header line: one or more ``[name]`` blocks with no brackets inside a name.
_HEADER_RE = re.compile(r"^(?:\[[^\[\]]*\])+$")
_HEADER_PART_RE = re.compile(r"\[([^\[\]]*)\]")

#: Characters that can never appear in a stored name or value (they would break the line
#: format or the generated shell script).
_FORBIDDEN_CHARS = ("\n", "\r", "\x00")


def _has_forbidden(text: str) -> bool:
    """Return True if ``text`` contains a newline, carriage return or NUL."""
    return any(ch in text for ch in _FORBIDDEN_CHARS)

#: Fragment root. Paths below it mirror a home directory, e.g.
#: ``skel-merge/.config/kdeglobals`` -> ``~/.config/kdeglobals``.
MERGE_DIR: Path = Path(__file__).resolve().parent / "vm" / "guest" / "skel-merge"

#: The KConfig writer both harnesses call. Looked up on the guest's PATH.
KWRITECONFIG: str = "kwriteconfig6"


class FragmentError(ValueError):
    """A fragment file is malformed or unsafe (see the module docstring for the rules)."""


@dataclass(frozen=True)
class ConfigEntry:
    """
    One key to write into one user config file.

    Attributes:
        file: Path relative to the home directory, POSIX separators, e.g.
            ``".config/kdeglobals"``. Never absolute, never containing ``..``, ``\\`` or NUL.
        groups: Group path from outermost to innermost, at least one element, e.g.
            ``("KDE",)`` or ``("Greeter", "Wallpaper", "org.kde.image", "General")``.
        key: Key name, non-empty.
        value: Value, possibly empty. Never contains a newline or NUL.

    Raises:
        FragmentError: from ``__post_init__`` when any field breaks the rules above
            (groups and key must also be free of ``[``, ``]``, newline and NUL).
    """

    file: str
    groups: tuple[str, ...]
    key: str
    value: str

    def __post_init__(self) -> None:
        # WHY validate here (not only in the parser): entries are also built directly by
        # callers, and ``file`` ends up in a path and a shell script.
        if not self.file or self.file.startswith("/") or "\\" in self.file or _has_forbidden(self.file):
            raise FragmentError(f"invalid target file: {self.file!r}")
        if any(part in ("", "..") for part in self.file.split("/")):
            raise FragmentError(f"invalid target file: {self.file!r}")
        if not self.groups:
            raise FragmentError("an entry needs at least one group")
        for group in self.groups:
            if not group or "[" in group or "]" in group or _has_forbidden(group):
                raise FragmentError(f"invalid group name: {group!r}")
        if not self.key or any(c in self.key for c in "[]=") or _has_forbidden(self.key):
            raise FragmentError(f"invalid key name: {self.key!r}")
        if _has_forbidden(self.value):
            raise FragmentError(f"invalid value for key {self.key!r}")


def parse_fragment(text: str, file: str) -> list[ConfigEntry]:
    """
    Parse one fragment file's text into entries for ``file``.

    Args:
        text: Fragment content (see module docstring for the format).
        file: Home-relative target path the entries belong to (validated as in
            :class:`ConfigEntry`).

    Returns:
        Entries in file order.

    Raises:
        FragmentError: malformed line, duplicate key, or invalid ``file``. The message
            names the 1-based line number.
    """
    entries: list[ConfigEntry] = []
    seen: set[tuple[tuple[str, ...], str]] = set()
    groups: tuple[str, ...] | None = None

    # WHY split on "\n" only and strip each line: str.splitlines() would also break on
    # exotic separators (form feed, U+2028) that KConfig does not treat as line ends.
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line[0] == "[":
            # A header must be a complete sequence of [..] blocks; anything else
            # (unclosed bracket, trailing text) is a typo that must not be guessed at.
            if not _HEADER_RE.match(line):
                raise FragmentError(f"line {number}: malformed group header")
            parts = tuple(_HEADER_PART_RE.findall(line))
            if any(not part.strip() for part in parts):
                raise FragmentError(f"line {number}: empty group name")
            groups = parts
            continue
        if groups is None:
            raise FragmentError(f"line {number}: key before any group header")
        if "=" not in line:
            raise FragmentError(f"line {number}: expected key=value")
        # Split on the FIRST "=" only so values such as URLs with query strings survive.
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise FragmentError(f"line {number}: empty key")
        if "[" in key or "]" in key:
            # Covers both Name[fi] (locale) and key[$e] (expansion flag): neither is
            # supported, and silently dropping the suffix would change the meaning.
            raise FragmentError(f"line {number}: locale suffix or flag in key is not supported")
        if "$" in key:
            raise FragmentError(f"line {number}: expansion flag in key is not supported")
        if (groups, key) in seen:
            raise FragmentError(f"line {number}: duplicate key {key!r}")
        seen.add((groups, key))
        try:
            entries.append(ConfigEntry(file, groups, key, value))
        except FragmentError as exc:
            raise FragmentError(f"line {number}: {exc}") from exc
    return entries


def load_fragments(root: Path = MERGE_DIR) -> list[ConfigEntry]:
    """
    Load every fragment file below ``root``.

    Every regular file below ``root`` (recursively, symlinks rejected) is one fragment;
    its path relative to ``root`` is the target ``file``. Files are processed in sorted
    relative-path order so the result is deterministic.

    Args:
        root: Fragment directory. A missing directory yields an empty list (a harness
            with nothing to merge is valid).

    Returns:
        All entries, grouped by file in sorted order, file order within each.

    Raises:
        FragmentError: any fragment is malformed, a symlink, or not UTF-8.
    """
    if not root.exists() and not root.is_symlink():
        return []
    if root.is_symlink() or not root.is_dir():
        raise FragmentError("fragment root is not a plain directory")

    # (relative posix path, absolute path) pairs, sorted for a deterministic result.
    found: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        # WHY reject symlinks: a link could point outside the fragment tree and make the
        # build read or merge arbitrary host files.
        if path.is_symlink():
            raise FragmentError(f"{rel}: symlinks are not allowed")
        if path.is_dir():
            continue
        if not path.is_file():
            raise FragmentError(f"{rel}: not a regular file")
        found.append((rel, path))

    entries: list[ConfigEntry] = []
    for rel, path in sorted(found):
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FragmentError(f"{rel}: not valid UTF-8") from exc
        try:
            entries.extend(parse_fragment(text, rel))
        except FragmentError as exc:
            raise FragmentError(f"{rel}: {exc}") from exc
    return entries


def _check_home(home: str) -> None:
    """
    Validate a home directory string for :func:`kwriteconfig_argv`.

    Args:
        home: Candidate home directory.

    Raises:
        ValueError: not absolute POSIX, ``/``, trailing slash, ``..`` segment, NUL or newline.
    """
    # WHY strict: the string is concatenated into a path that is written as root (image
    # build) or by the desktop user; relative or traversing forms could escape the target.
    if not home.startswith("/") or home == "/" or home.endswith("/"):
        raise ValueError("home must be an absolute POSIX path without trailing slash")
    if _has_forbidden(home) or ".." in home.split("/"):
        raise ValueError("home contains a forbidden component")


def kwriteconfig_argv(entry: ConfigEntry, home: str) -> list[str]:
    """
    Build the ``kwriteconfig6`` argument list that writes ``entry`` below ``home``.

    Shape: ``[KWRITECONFIG, "--file", f"{home}/{entry.file}", "--group", g1, ...,
    "--group", gN, "--key", entry.key, entry.value]``. ``--file`` gets an absolute path so
    the call does not depend on the caller's XDG_CONFIG_HOME. Meant to be run as the
    file's owner (a root-run call would leave a root-owned file in a user's home).

    Args:
        entry: The entry to write.
        home: Absolute home directory, POSIX form, no trailing slash (``/etc/skel`` is
            valid, it is the build-time target).

    Returns:
        The argument list (never a shell string).

    Raises:
        ValueError: ``home`` is not absolute POSIX, ends with ``/`` (other than ``/``
            itself, which is rejected too), or contains ``..``/NUL/newline.
    """
    _check_home(home)
    argv = [KWRITECONFIG, "--file", f"{home}/{entry.file}"]
    for group in entry.groups:
        argv += ["--group", group]
    argv += ["--key", entry.key, entry.value]
    return argv


def render_shell_script(entries: list[ConfigEntry], home: str) -> str:
    """
    Render a POSIX sh script that applies ``entries`` below ``home``.

    For the image build, where the merge runs inside a container RUN step. The script
    starts with ``#!/bin/sh`` and ``set -eu``, then one line per entry: the
    :func:`kwriteconfig_argv` arguments, each quoted with ``shlex.quote``. An empty
    ``entries`` list yields a script that only does ``set -eu`` (valid no-op).

    Args:
        entries: Entries to apply, in order.
        home: As for :func:`kwriteconfig_argv`.

    Returns:
        The script text, ``\\n`` line endings, single trailing newline.

    Raises:
        ValueError: invalid ``home`` (see :func:`kwriteconfig_argv`).
    """
    _check_home(home)
    lines = ["#!/bin/sh", "set -eu"]
    # WHY shlex.quote on every word: values come from data files and may hold spaces,
    # quotes or "$"; quoting keeps them literal so no value can become shell code.
    lines += [" ".join(shlex.quote(arg) for arg in kwriteconfig_argv(e, home)) for e in entries]
    return "\n".join(lines) + "\n"
