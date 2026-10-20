"""Boot menu branding: no upstream brand in titles, functional lines unchanged vs git HEAD."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from design.validate import load_tokens

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "iso" / "profile"
BOOT_FILES = sorted(
    [p for d in ("syslinux", "efiboot", "grub") for p in (PROFILE / d).rglob("*") if p.suffix in (".cfg", ".conf")]
)
BRAND = "Arch Linux"
TOKEN = "@DISTRO_DISPLAY_NAME@"

# A line is a "title" line (allowed to change) if it is one of these label forms or
# the descriptive TEXT HELP body lines that name the system.
TITLE_RE = re.compile(r"^(MENU TITLE|MENU LABEL|title\s|menuentry )")


def _head(path: Path) -> list[str] | None:
    """Return the file's lines at git HEAD, or None if it is not tracked there."""
    rel = path.relative_to(ROOT).as_posix()
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, text=True, check=False)
    return r.stdout.splitlines() if r.returncode == 0 else None


def _is_title_like(line: str) -> bool:
    """True for lines that carry user-visible naming (titles, labels, help prose)."""
    return bool(TITLE_RE.match(line)) or BRAND in line or TOKEN in line


def test_boot_files_found() -> None:
    """Guard against the glob silently matching nothing."""
    assert len(BOOT_FILES) >= 10


@pytest.mark.parametrize("path", BOOT_FILES, ids=lambda p: p.relative_to(PROFILE).as_posix())
def test_no_upstream_brand_in_boot_menus(path: Path) -> None:
    """No boot menu file names the upstream distribution as a brand."""
    assert BRAND not in path.read_text()


@pytest.mark.parametrize("path", BOOT_FILES, ids=lambda p: p.relative_to(PROFILE).as_posix())
def test_functional_lines_unchanged(path: Path) -> None:
    """Everything except titles/labels/help prose (and menu colours) is identical to HEAD."""
    old = _head(path)
    if old is None:
        pytest.skip("not tracked at HEAD")
    new = path.read_text().splitlines()

    def functional(lines: list[str]) -> list[str]:
        return [ln for ln in lines if not _is_title_like(ln) and not ln.startswith(("MENU COLOR", "#"))]

    assert functional(new) == functional(old)
    # Title-like lines must not appear or vanish: same count.
    assert sum(map(_is_title_like, new)) == sum(map(_is_title_like, old))


def test_title_lines_use_display_name_token() -> None:
    """Every distribution boot entry title (those naming %ARCH%) uses the template token."""
    checked = 0
    for path in BOOT_FILES:
        for ln in path.read_text().splitlines():
            if TITLE_RE.match(ln) and "%ARCH%" in ln:
                assert TOKEN in ln, f"{path.name}: {ln}"
                checked += 1
    assert checked >= 11
    assert f"MENU TITLE {TOKEN}" in (PROFILE / "syslinux" / "archiso_head.cfg").read_text()


def test_menu_colours_are_token_colours() -> None:
    """Every MENU COLOR hex pair is a colour.dark token colour (RGB) with its own alpha byte."""
    palette = load_tokens(ROOT / "design" / "tokens.json")["color"]["dark"]
    allowed = {palette[k].lstrip("#").upper()[:6] for k in ("window", "surface", "text", "text_secondary", "accent")}
    seen = 0
    for ln in (PROFILE / "syslinux" / "archiso_head.cfg").read_text().splitlines():
        if ln.startswith("MENU COLOR"):
            for m in re.finditer(r"#[0-9a-fA-F]{2}([0-9a-fA-F]{6})", ln):
                assert m.group(1).upper() in allowed, ln
                seen += 1
    assert seen == 18
