"""Tests for the live-medium login banners (/etc/motd and /etc/issue).

They must carry the product name through the build-time display-name token, must not
fall back to upstream distribution text or wiki links, and must be LF-only (a CR in a
file the build stages would leak into the console banner).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ETC = ROOT / "iso" / "profile" / "airootfs" / "etc"
BS = chr(92)
TOKEN = "@DISTRO_DISPLAY_NAME@"
BANNERS = ["motd", "issue"]
SCRIPTS = [ROOT / "iso" / "build_iso.sh", ROOT / "release" / "build_iso_host.sh"]


@pytest.mark.parametrize("name", BANNERS)
def test_banner_carries_product_token(name: str) -> None:
    """The banner names the product via the token the build substitutes."""
    assert TOKEN in (ETC / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", BANNERS)
def test_banner_has_no_upstream_branding(name: str) -> None:
    """No upstream distribution name or wiki link may sneak back in."""
    text = (ETC / name).read_text(encoding="utf-8").lower()
    for banned in ("arch linux", "archlinux.org", "installation_guide", "installation guide"):
        assert banned not in text


@pytest.mark.parametrize("name", BANNERS)
def test_banner_is_lf_only(name: str) -> None:
    """CRLF line endings would show up as stray characters on the console."""
    assert b"\r\n" not in (ETC / name).read_bytes()


def test_motd_keeps_connectivity_hints() -> None:
    """The still-true network hints survive the rewrite."""
    text = (ETC / "motd").read_text(encoding="utf-8")
    for hint in ("iwctl", "mmcli", "DHCP"):
        assert hint in text


def test_issue_keeps_getty_escapes() -> None:
    r"""agetty expands \r (kernel release) and \l (tty); the file must keep them literal."""
    assert BS + "r (" + BS + "l)" in (ETC / "issue").read_text(encoding="utf-8")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_both_build_scripts_substitute_banners(script: Path) -> None:
    """Both build paths must stage the banners with the display-name substitution."""
    text = script.read_text(encoding="utf-8")
    assert "airootfs/etc/motd" in text
    assert "airootfs/etc/issue" in text
    assert "@DISTRO_DISPLAY_NAME@" in text
