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


def test_look_and_feel_package_is_kept() -> None:
    """The logout dialog's Look-and-Feel package selection is unaffected by the style change."""
    assert _kde_group()["LookAndFeelPackage"] == "kuura"
