"""Tests for design.generate_bootsplash and the committed boot menu splash."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from design.generate_bootsplash import DEFAULT_OUT, HEIGHT, WIDTH, generate_bootsplash, main, render
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


@pytest.fixture(scope="module")
def tokens() -> dict:
    """Real, validated project tokens."""
    return load_tokens(TOKENS_PATH)


def test_size_and_mode(tokens, tmp_path) -> None:
    """syslinux vesamenu needs exactly 640x480; output is plain 8-bit RGB PNG."""
    out = generate_bootsplash(tokens, tmp_path / "s.png", "kuura")
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (640, 480) == (WIDTH, HEIGHT)
        assert img.mode == "RGB"


def test_deterministic(tokens, tmp_path) -> None:
    """Same tokens and name give identical bytes."""
    a = generate_bootsplash(tokens, tmp_path / "a.png", "kuura").read_bytes()
    b = generate_bootsplash(tokens, tmp_path / "b.png", "kuura").read_bytes()
    assert a == b


def test_colours_come_from_tokens(tokens) -> None:
    """Corners are the gradient ends (window/surface); the name and accent rule are drawn."""
    img = render(tokens, "kuura")
    assert img.getpixel((0, 0)) == (0x15, 0x18, 0x1C)
    assert img.getpixel((0, HEIGHT - 1)) == (0x1C, 0x20, 0x25)
    colours = {c for _n, c in img.getcolors(maxcolors=1 << 20)}
    assert (0x4F, 0xB3, 0xC8) in colours  # accent rule
    assert (0xE6, 0xE9, 0xED) in colours  # wordmark text


def test_name_changes_image(tokens) -> None:
    """The distribution name is actually drawn."""
    assert render(tokens, "kuura").tobytes() != render(tokens, "other").tobytes()


@pytest.mark.parametrize("bad", ["", "Kuura", "a b", "../x"])
def test_invalid_name_rejected(tokens, bad) -> None:
    """Names outside [a-z0-9_-]+ raise ValueError."""
    with pytest.raises(ValueError):
        render(tokens, bad)


def test_cli_rejects_out_outside_project(tmp_path) -> None:
    """--out outside the project is refused (exit 2) and nothing is written."""
    target = tmp_path / "x.png"
    assert main(["--out", str(target)]) == 2
    assert not target.exists()


def test_committed_splash_is_up_to_date(tokens) -> None:
    """The PNG committed in the profile equals a fresh render for the default name."""
    with Image.open(DEFAULT_OUT) as committed:
        assert committed.convert("RGB").tobytes() == render(tokens, "kuura").tobytes()
