"""Behaviour tests for harness.skelmerge (fragment parsing, loading and rendering)."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from harness import skelmerge
from harness.skelmerge import (
    ConfigEntry,
    FragmentError,
    kwriteconfig_argv,
    load_fragments,
    parse_fragment,
    render_shell_script,
)

F = ".config/kdeglobals"


def test_parse_happy_path_keeps_file_order() -> None:
    """Groups and keys come back in file order with the target file attached."""
    text = "[KDE]\nB=1\nA=2\n\n[Other]\nC=3\n"
    assert parse_fragment(text, F) == [
        ConfigEntry(F, ("KDE",), "B", "1"),
        ConfigEntry(F, ("KDE",), "A", "2"),
        ConfigEntry(F, ("Other",), "C", "3"),
    ]


def test_parse_value_with_equals_and_whitespace_stripping() -> None:
    """Only the first "=" splits; whitespace around key, "=" and value is stripped."""
    (entry,) = parse_fragment("[G]\n  key  =  a=b=c  \n", F)
    assert (entry.key, entry.value) == ("key", "a=b=c")


def test_parse_empty_value_is_allowed() -> None:
    """A key with nothing after "=" yields an empty value."""
    (entry,) = parse_fragment("[G]\nk=\n", F)
    assert entry.value == ""


def test_parse_nested_groups() -> None:
    """Consecutive brackets form a nested group path."""
    (entry,) = parse_fragment("[A][B][C]\nk=v\n", F)
    assert entry.groups == ("A", "B", "C")


def test_parse_ignores_comments_and_blank_lines() -> None:
    """Lines starting with # or ; (even indented) and blank lines are skipped."""
    text = "# c\n; c\n\n   # indented\n[G]\n; c\nk=v\n"
    assert parse_fragment(text, F) == [ConfigEntry(F, ("G",), "k", "v")]


def test_parse_handles_crlf_and_empty_text() -> None:
    """CRLF line ends are tolerated; empty text has no entries."""
    assert parse_fragment("[G]\r\nk=v\r\n", F) == [ConfigEntry(F, ("G",), "k", "v")]
    assert parse_fragment("", F) == []


def test_same_key_in_different_groups_is_not_a_duplicate() -> None:
    """Duplicate detection is per (groups, key)."""
    assert len(parse_fragment("[A]\nk=1\n[B]\nk=2\n", F)) == 2


@pytest.mark.parametrize(
    "text",
    [
        "k=v\n",  # key before header
        "[G\nk=v\n",  # unclosed header
        "[G]x\nk=v\n",  # trailing text after header
        "[]\nk=v\n",  # empty group
        "[A][]\nk=v\n",  # empty nested group
        "[G]\n=v\n",  # empty key
        "[G]\nnovalue\n",  # no "="
        "[G]\nName[fi]=v\n",  # locale suffix
        "[G]\nName[$e]=v\n",  # expansion flag
        "[G]\nna$me=v\n",  # dollar in key
        "[G]\nk=1\nk=2\n",  # duplicate
        "[A][B]\nk=1\n[A][B]\nk=2\n",  # duplicate across re-opened group
    ],
)
def test_parse_rejects_malformed(text: str) -> None:
    """Every rule violation raises FragmentError."""
    with pytest.raises(FragmentError):
        parse_fragment(text, F)


def test_parse_error_names_line_number() -> None:
    """The message carries the 1-based line number of the offending line."""
    with pytest.raises(FragmentError, match="line 3"):
        parse_fragment("[G]\nk=v\nbad\n", F)


@pytest.mark.parametrize("bad", ["", "/abs", "a/../b", "..", "a\\b", "a//b", "a\nb", "a\x00b", "a/"])
def test_invalid_file_rejected(bad: str) -> None:
    """Absolute, traversing, backslash, NUL/newline and empty-segment files are refused."""
    with pytest.raises(FragmentError):
        parse_fragment("[G]\nk=v\n", bad)
    with pytest.raises(FragmentError):
        ConfigEntry(bad, ("G",), "k", "v")


@pytest.mark.parametrize("value", ["a\nb", "a\rb", "a\x00b"])
def test_entry_rejects_control_chars_in_value(value: str) -> None:
    """Newline, CR and NUL in a value are refused."""
    with pytest.raises(FragmentError):
        ConfigEntry(F, ("G",), "k", value)


def test_entry_rejects_bad_groups_and_key() -> None:
    """Empty/bracketed names and an empty group tuple are refused."""
    for groups, key in [((), "k"), (("",), "k"), (("a[b",), "k"), (("G",), ""), (("G",), "k]")]:
        with pytest.raises(FragmentError):
            ConfigEntry(F, groups, key, "v")


def test_load_missing_root_is_empty(tmp_path: Path) -> None:
    """A missing fragment directory means nothing to merge."""
    assert load_fragments(tmp_path / "nope") == []


def test_load_sorted_and_relative(tmp_path: Path) -> None:
    """Files load in sorted relative-path order, target path relative with POSIX separators."""
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "zrc").write_text("[Z]\nz=1\n", encoding="utf-8")
    (tmp_path / ".config" / "arc").write_text("[A]\na=1\na2=2\n", encoding="utf-8")
    entries = load_fragments(tmp_path)
    assert [(e.file, e.key) for e in entries] == [
        (".config/arc", "a"),
        (".config/arc", "a2"),
        (".config/zrc", "z"),
    ]


def test_load_empty_dir(tmp_path: Path) -> None:
    """An existing but empty directory yields no entries."""
    assert load_fragments(tmp_path) == []


def test_load_error_names_file(tmp_path: Path) -> None:
    """A malformed fragment's error message names the file."""
    (tmp_path / "badrc").write_text("k=v\n", encoding="utf-8")
    with pytest.raises(FragmentError, match="badrc"):
        load_fragments(tmp_path)


def test_load_rejects_non_utf8(tmp_path: Path) -> None:
    """Bytes that are not UTF-8 are refused, not guessed."""
    (tmp_path / "rc").write_bytes(b"[G]\nk=\xff\xfe\n")
    with pytest.raises(FragmentError):
        load_fragments(tmp_path)


def test_load_rejects_symlink_fragment(tmp_path: Path) -> None:
    """A symlink inside the fragment tree is refused."""
    target = tmp_path / "outside"
    target.write_text("[G]\nk=v\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "link").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this system")
    with pytest.raises(FragmentError):
        load_fragments(root)


def test_load_root_that_is_a_file_rejected(tmp_path: Path) -> None:
    """A root that exists but is not a directory is an error."""
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(FragmentError):
        load_fragments(f)


def test_shipped_fragments_load() -> None:
    """The real fragments in the repository parse and hold the test-only keys."""
    entries = {(e.file, e.groups, e.key, e.value) for e in load_fragments()}
    assert (".config/kdeglobals", ("KDE",), "AnimationDurationFactor", "0") in entries
    assert (".config/kscreenlockerrc", ("Daemon",), "Autolock", "false") in entries


def test_kwriteconfig_argv_exact_shape() -> None:
    """The argument list has exactly the documented shape."""
    entry = ConfigEntry(".config/x", ("A", "B"), "k", "v w")
    assert kwriteconfig_argv(entry, "/etc/skel") == [
        skelmerge.KWRITECONFIG,
        "--file",
        "/etc/skel/.config/x",
        "--group",
        "A",
        "--group",
        "B",
        "--key",
        "k",
        "v w",
    ]


def test_kwriteconfig_argv_empty_value_kept() -> None:
    """An empty value is still passed as the final argument."""
    argv = kwriteconfig_argv(ConfigEntry("f", ("G",), "k", ""), "/home/u")
    assert argv[-1] == ""


@pytest.mark.parametrize("home", ["/etc/skel", "/home/user", "/a..b"])
def test_home_accepted(home: str) -> None:
    """Absolute POSIX homes without trailing slash are accepted."""
    kwriteconfig_argv(ConfigEntry("f", ("G",), "k", "v"), home)
    render_shell_script([], home)


@pytest.mark.parametrize("home", ["etc/skel", "/etc/skel/", "/", "/a/../b", "", "/a\nb", "/a\x00b"])
def test_home_rejected(home: str) -> None:
    """Relative, trailing-slash, root, traversing and control-char homes are refused."""
    entry = ConfigEntry("f", ("G",), "k", "v")
    with pytest.raises(ValueError):
        kwriteconfig_argv(entry, home)
    with pytest.raises(ValueError):
        render_shell_script([entry], home)


def test_render_empty_list() -> None:
    """No entries gives a valid no-op script."""
    assert render_shell_script([], "/etc/skel") == "#!/bin/sh\nset -eu\n"


def test_render_script_structure_and_quoting() -> None:
    """Shebang, set -eu, one line per entry, hostile values stay a single literal word."""
    value = "it's a \"test\" $HOME `x` ; rm -rf /"
    entries = [ConfigEntry("f", ("G",), "k", value), ConfigEntry("f", ("G",), "k2", "plain")]
    script = render_shell_script(entries, "/etc/skel")
    lines = script.split("\n")
    assert lines[0] == "#!/bin/sh"
    assert lines[1] == "set -eu"
    assert script.endswith("\n") and not script.endswith("\n\n")
    assert "\r" not in script
    assert len(lines) == 5  # shebang, set, two entries, trailing empty string
    # Round trip through shlex proves the quoting keeps the value one literal word.
    assert shlex.split(lines[2]) == kwriteconfig_argv(entries[0], "/etc/skel")
    assert shlex.split(lines[3]) == kwriteconfig_argv(entries[1], "/etc/skel")
