"""
Checks for the installer's post-install removal of the live-only local repository.

WHY: the live ISO carries a local signed repository at /srv/repo plus a matching
pacman.conf section so the live session can install from local media. The installed
system must not keep either (docs/ISO_CONTRACT.md, decision of 2026-10-19), otherwise
every `pacman -Syu` fails against absent media.
"""

from __future__ import annotations

import importlib.util
import re
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

PKG = Path(__file__).resolve().parent.parent / "packages" / "kuura-installer-config"
SCRIPT = PKG / "helpers" / "strip_live_repo.py"
SHELLPROCESS = PKG / "calamares-defaults" / "modules" / "shellprocess.conf"
SETTINGS = PKG / "calamares-defaults" / "settings.conf.in"
PKGBUILD = PKG / "PKGBUILD"


def _load() -> ModuleType:
    """Import the helper script by path (its directory is not a Python package)."""
    spec = importlib.util.spec_from_file_location("strip_live_repo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["strip_live_repo"] = module
    spec.loader.exec_module(module)
    return module


strip = _load()

HEAD = "[options]\nHoldPkg = pacman glibc\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n\n"
SECTION = "[demo]\nSigLevel = Required\nServer = file:///srv/repo/x86_64\n"


def test_section_at_end_is_removed() -> None:
    """The shipped layout: the repo section is the last one in the file."""
    text = HEAD + "# live repo\n" + SECTION
    assert strip.remove_section(text, "demo") == HEAD + "# live repo\n"


def test_section_in_middle_leaves_neighbours_untouched() -> None:
    """Sections before and after, including the next section's own comment, survive."""
    tail = "# extra repo\n[extra]\nInclude = /etc/pacman.d/mirrorlist\n"
    text = HEAD + SECTION + "\n" + tail
    assert strip.remove_section(text, "demo") == HEAD + "\n" + tail


def test_absent_section_is_a_noop() -> None:
    """Idempotent: running twice, or on a conf without the section, changes nothing."""
    assert strip.remove_section(HEAD, "demo") == HEAD
    once = strip.remove_section(HEAD + SECTION, "demo")
    assert strip.remove_section(once, "demo") == once


def test_commented_out_header_is_not_a_section() -> None:
    """A commented example header must not start or end a removal."""
    text = HEAD + "#[demo]\n#Server = file:///x\n" + SECTION
    assert strip.remove_section(text, "demo") == HEAD + "#[demo]\n#Server = file:///x\n"


def test_name_must_match_exactly() -> None:
    """[demo-extra] and [demo2] are different sections from [demo]."""
    text = "[demo-extra]\nServer = a\n[demo2]\nServer = b\n"
    assert strip.remove_section(text, "demo") == text


def test_header_with_surrounding_whitespace_is_matched() -> None:
    """pacman tolerates whitespace around the header; so does the stripper."""
    assert strip.remove_section("[core]\nA = 1\n  [demo]  \nB = 2\n", "demo") == "[core]\nA = 1\n"


def test_comments_inside_the_section_go_with_it() -> None:
    """Comments between the header and its last option belong to the section's body."""
    text = "[demo]\n# why\nSigLevel = Required\n\n[core]\nA = 1\n"
    assert strip.remove_section(text, "demo") == "\n[core]\nA = 1\n"


def test_crlf_and_missing_final_newline() -> None:
    """Odd line endings must not break the section boundary detection."""
    text = "[core]\r\nA = 1\r\n[demo]\r\nServer = x"
    assert strip.remove_section(text, "demo") == "[core]\r\nA = 1\r\n"


@pytest.mark.parametrize("name", ["options", "", "a b", "x]y", "[demo]", "../etc", "a\nb"])
def test_invalid_or_protected_names_are_rejected(name: str) -> None:
    """[options] holds global settings and must never be removed; junk names are errors."""
    with pytest.raises(ValueError):
        strip.remove_section(HEAD + SECTION, name)


def test_main_edits_file_in_place_and_keeps_mode(tmp_path: Path) -> None:
    """main() rewrites the file atomically and preserves its permission bits."""
    conf = tmp_path / "pacman.conf"
    conf.write_text(HEAD + SECTION, encoding="utf-8")
    conf.chmod(0o640)
    assert strip.main(["demo", str(conf)]) == 0
    assert conf.read_text(encoding="utf-8") == HEAD
    if sys.platform != "win32":
        assert stat.S_IMODE(conf.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["pacman.conf"]  # no temp leftovers


def test_main_errors_are_generic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing file or bad name gives a non-zero exit and no path/traceback on stderr."""
    missing = tmp_path / "nope.conf"
    assert strip.main(["demo", str(missing)]) != 0
    assert strip.main(["options", str(missing)]) != 0
    err = capsys.readouterr().err
    assert str(tmp_path) not in err and "Traceback" not in err


# ---- shipped configuration ----


def _script_lines() -> list[str]:
    """Return shellprocess.conf's command list."""
    data = yaml.safe_load(SHELLPROCESS.read_text(encoding="utf-8"))
    return [str(c) for c in data["script"]]


def test_shellprocess_strips_the_pacman_conf_section() -> None:
    """One entry invokes the helper with the (substituted) distro name."""
    hits = [c for c in _script_lines() if "strip-live-repo" in c]
    assert len(hits) == 1
    assert "@NAME@" in hits[0]
    assert not hits[0].startswith("-"), "a failed strip must fail the install, not be ignored"


def test_shellprocess_removes_repo_dir_and_sync_db() -> None:
    """/srv/repo and the repo's cached sync database are deleted from the target."""
    lines = _script_lines()
    assert "-rm -rf /srv/repo" in lines
    assert any(c.startswith("-rm -f /var/lib/pacman/sync/@NAME@.db") for c in lines)


def test_shellprocess_does_not_touch_the_keyring() -> None:
    """The ISO never imports the repo key into a keyring that reaches the target."""
    assert not any("pacman-key" in c for c in _script_lines())


def test_shellprocess_runs_before_packages_in_the_sequence() -> None:
    """The cleanup runs after unpackfs (files exist) and before any pacman step."""
    seq = re.findall(r"^  - (\w[\w@-]*)\s*$", SETTINGS.read_text(encoding="utf-8"), re.M)
    assert seq.index("unpackfs") < seq.index("shellprocess") < seq.index("packages")


def test_pkgbuild_installs_helper_and_substitutes_name() -> None:
    """The helper ships executable and shellprocess.conf gets @NAME@ replaced at build."""
    text = PKGBUILD.read_text(encoding="utf-8")
    assert "strip_live_repo.py" in text
    assert re.search(r"sed .*@NAME@.*shellprocess\.conf", text)
    assert re.search(r"^depends=\(.*'python'", text, re.M)


def test_shellprocess_timeout_tolerates_a_slow_initramfs_step() -> None:
    """
    REGRESSION: the mkinitcpio step exceeded the old 30 s limit on a loaded host and
    aborted the install. The per-command timeout must leave minutes of headroom.
    """
    data = yaml.safe_load(SHELLPROCESS.read_text(encoding="utf-8"))
    assert any("mkinitcpio" in line for line in _script_lines())
    assert data["timeout"] >= 300
