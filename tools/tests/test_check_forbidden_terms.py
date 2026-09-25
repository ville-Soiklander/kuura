"""Tests for check_forbidden_terms module."""

import hashlib
from pathlib import Path

import pytest

from tools import check_forbidden_terms as cft


def digest(word: str) -> str:
    """SHA-256 hash of a word."""
    return hashlib.sha256(word.encode("utf-8")).hexdigest()


HASHES = {digest("zebrafish")}


def test_line_hits():
    """line_hits matches case-insensitive, adjacent words, separators."""
    assert cft.line_hits("Zebrafish", HASHES)
    assert cft.line_hits("zebra fish", HASHES)
    assert cft.line_hits("zebra_fish", HASHES)
    assert not cft.line_hits("zebrafishy", HASHES)
    assert not cft.line_hits("", HASHES)
    assert not cft.line_hits("zebrafish", set())


def test_scan_text():
    """scan_text returns 1-based line numbers with hits."""
    assert cft.scan_text("ok\nzebrafish\nok\nZebra Fish\n", HASHES) == [2, 4]
    assert cft.scan_text("", HASHES) == []


def test_load_hashes(tmp_path):
    """load_hashes skips comments, blank lines, lowercases digests."""
    f = tmp_path / "h.txt"
    f.write_text(f"#c\n{digest('x').upper()}\n\n{digest('y')}\n")
    h = cft.load_hashes(f)
    assert digest("x").lower() in h and digest("y").lower() in h
    with pytest.raises(FileNotFoundError):
        cft.load_hashes(Path("/x/y"))


def test_is_text_file(tmp_path):
    """is_text_file returns False for binary, missing, or large files."""
    t = tmp_path / "t.txt"
    t.write_text("hi")
    assert cft.is_text_file(t)

    b = tmp_path / "b.bin"
    b.write_bytes(b"x\x00y")
    assert not cft.is_text_file(b)
    assert not cft.is_text_file(Path("/x"))


def test_main(tmp_path, monkeypatch, capsys):
    """main returns 0/1/2 and prints path:line for hits only."""
    hf = tmp_path / "h.txt"
    hf.write_text(digest("zebrafish"))
    monkeypatch.setattr(cft, "HASH_FILE", hf)

    cf = tmp_path / "c.txt"
    cf.write_text("ok")
    assert cft.main([str(cf)]) == 0

    df = tmp_path / "d.txt"
    df.write_text("line1\nzebrafish line2\n")
    assert cft.main([str(df)]) == 1
    out = capsys.readouterr().out
    assert ":2: forbidden term" in out
    assert "zebrafish" not in out

    monkeypatch.setattr(cft, "HASH_FILE", tmp_path / "x")
    assert cft.main([str(cf)]) == 2


def test_negative():
    """Plain text returns no hits on real hash file."""
    h = cft.load_hashes(cft.HASH_FILE)
    assert not cft.line_hits("plain text", h)
