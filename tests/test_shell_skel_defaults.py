"""Checks on the per-user defaults the kuura-shell package ships in /etc/skel."""

from __future__ import annotations

import configparser
from pathlib import Path

KDEGLOBALS = Path(__file__).resolve().parent.parent / "packages" / "kuura-shell" / "skel" / ".config" / "kdeglobals"


def _kde_group() -> configparser.SectionProxy:
    """
    Parse the shipped kdeglobals and return its [KDE] group.

    Returns:
        The [KDE] section.

    Raises:
        KeyError: the file has no [KDE] group.
    """
    parser = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",))
    parser.optionxform = str  # KConfig keys are case-sensitive
    parser.read(KDEGLOBALS, encoding="utf-8")
    return parser["KDE"]


def test_widget_style_is_breeze() -> None:
    """
    The product must not select Kvantum while its generated Kvantum themes ship no SVG.

    Without an SVG Kvantum draws every widget with its own dark built-in default, so
    light mode showed dark buttons and fields on light windows (2026-10-17). Breeze
    takes its colours from the shipped colour scheme in both modes.
    """
    assert _kde_group()["widgetStyle"] == "Breeze"


KWINRC = KDEGLOBALS.parent / "kwinrc"


def _kwinrc() -> configparser.ConfigParser:
    """
    Parse the shipped kwinrc.

    Returns:
        The parsed file with case-sensitive keys (KConfig semantics).
    """
    parser = configparser.ConfigParser(interpolation=None, comment_prefixes=("#",), allow_no_value=True)
    parser.optionxform = str
    parser.read(KWINRC, encoding="utf-8")
    return parser


def test_window_buttons_live_in_the_decoration_group() -> None:
    """
    The button layout must sit in [org.kde.kdecoration2], close/minimize/maximize on the left.

    KWin reads the layout from the decoration settings group; the same keys under
    [Windows] are silently ignored, which left KDE's default (menu icon on the left,
    buttons on the right) on screen.
    """
    group = _kwinrc()["org.kde.kdecoration2"]
    assert group["ButtonsOnLeft"] == "XIA"
    assert group["ButtonsOnRight"] == ""


def test_dead_windows_group_has_no_button_keys() -> None:
    """The ignored [Windows] copy of the layout must not come back."""
    parser = _kwinrc()
    leftovers = [k for k in parser["Windows"] if k.startswith("ButtonsOn")] if parser.has_section("Windows") else []
    assert leftovers == []


def test_look_and_feel_package_is_kept() -> None:
    """The logout dialog's Look-and-Feel package selection is unaffected by the style change."""
    assert _kde_group()["LookAndFeelPackage"] == "kuura"
