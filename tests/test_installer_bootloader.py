"""
Checks for the installer's UEFI bootloader configuration.

WHY: Calamares' bootloader module (v3.4.2, main.py ``efi_label``) takes the EFI
directory name from ``efiBootloaderId`` in bootloader.conf and, only when that key
is absent, from ``bootloaderEntryName`` in branding.desc. This project's branding
has no such entry and the vendored bootloader.conf left the key commented out, so
every UEFI install ran ``grub-install --bootloader-id=`` (empty), GRUB landed
directly in ``EFI/`` and the fallback copy of ``EFI/<id>/grubx64.efi`` failed with
FileNotFoundError ("Bad main script file"). BIOS never calls ``efi_label``, which is
why only UEFI installs failed.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packages" / "kuura-installer-config"
BOOTLOADER = PKG / "calamares-defaults" / "modules" / "bootloader.conf"
PKGBUILD = PKG / "PKGBUILD"

# Same shape design/generate.py accepts for the distro name (the value the
# PKGBUILD substitutes for @NAME@).
NAME = "kuura"


def _rendered_bootloader(name: str = NAME) -> dict:
    """bootloader.conf exactly as the PKGBUILD's sed installs it."""
    return yaml.safe_load(BOOTLOADER.read_text(encoding="utf-8").replace("@NAME@", name))


def _effective_efi_id(config: dict, branding: dict) -> str:
    """
    Mirror Calamares 3.4.2 ``efi_label``: the config key wins, else the branding entry.

    Raises:
        KeyError: neither source has a value (Calamares raises the same).
    """
    if "efiBootloaderId" in config:
        return str(config["efiBootloaderId"])
    return str(branding["strings"]["bootloaderEntryName"])


def _branding() -> dict:
    """The branding.desc this project generates (design/generators/calamares_branding.py)."""
    from design.generators import calamares_branding
    from design.validate import load_tokens

    return yaml.safe_load(calamares_branding.render(load_tokens(ROOT / "design" / "tokens.json"), NAME))


def test_uefi_bootloader_id_is_never_empty() -> None:
    """The id grub-install receives must be a real, non-empty directory name."""
    efi_id = _effective_efi_id(_rendered_bootloader(), _branding())
    assert efi_id == NAME


def test_efi_bootloader_id_is_a_plain_placeholder_for_the_distro_name() -> None:
    """
    The id is the distro name (no ${SERIAL}/${RANDOM}/${PHRASE} suffix: a fixed
    directory keeps EFI/<name>/ stable across reinstalls) and contains nothing
    Calamares' sanitizer would rewrite (space, slash).
    """
    raw = yaml.safe_load(BOOTLOADER.read_text(encoding="utf-8"))
    assert raw["efiBootloaderId"] == "@NAME@"
    rendered = _rendered_bootloader("my-distro_2")
    assert re.fullmatch(r"[a-z0-9_-]+", rendered["efiBootloaderId"])


def test_grub_with_fallback_stays_the_uefi_loader() -> None:
    """The fix does not change the loader choice or the fallback copy."""
    config = _rendered_bootloader()
    assert config["efiBootLoader"] == "grub"
    assert config["installEFIFallback"] is True
    assert config["installHybridGRUB"] is False


def test_pkgbuild_substitutes_the_name_into_bootloader_conf() -> None:
    """bootloader.conf goes through the @NAME@ sed, not the verbatim install loop."""
    text = PKGBUILD.read_text(encoding="utf-8")
    assert re.search(r'sed "s/@NAME@/\$\{DISTRO_NAME\}/g" "\$defaults/modules/bootloader\.conf"', text)
    loop = re.search(r"local other_modules=\((.*?)\)", text, re.S)
    assert loop is not None
    assert "bootloader" not in loop.group(1).split()


def test_pkgrel_bumped_for_the_fix() -> None:
    """The rebuilt package must be distinguishable from the broken 0.1.0-3."""
    match = re.search(r"^pkgrel=(\d+)$", PKGBUILD.read_text(encoding="utf-8"), re.M)
    assert match is not None and int(match.group(1)) >= 4
