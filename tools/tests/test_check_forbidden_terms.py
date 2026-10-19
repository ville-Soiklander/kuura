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


# ---------------------------------------------------------------------------
# Per-file exemptions.
# WHY neutral words: the checker scans this file too, so the tests build their
# digests from harmless words and never spell a real forbidden name.
# ---------------------------------------------------------------------------

EXEMPT_NAME = "TRADEMARKS.md"


def test_exemptions_constant_shape():
    """EXEMPTIONS has exactly one key with exactly one digest, present in the real list."""
    assert set(cft.EXEMPTIONS) == {EXEMPT_NAME}
    digests = cft.EXEMPTIONS[EXEMPT_NAME]
    assert isinstance(digests, frozenset)
    assert len(digests) == 1
    assert digests <= cft.load_hashes(cft.HASH_FILE)


def test_line_hits_exempt_single_word():
    """An exempted single-word digest is not a hit; a non-exempted one still is."""
    hashes = {digest("zebrafish"), digest("quokka")}
    exempt = frozenset({digest("zebrafish")})
    assert cft.line_hits("zebrafish", hashes)  # default unchanged
    assert not cft.line_hits("zebrafish", hashes, exempt)
    assert not cft.line_hits("ZebraFish", hashes, exempt)
    assert cft.line_hits("quokka", hashes, exempt)
    # Other forbidden digest on the same line is still found.
    assert cft.line_hits("zebrafish and quokka", hashes, exempt)
    assert not cft.line_hits("zebrafish and nothing", hashes, exempt)
    assert not cft.line_hits("", hashes, exempt)


def test_line_hits_exempt_pairs():
    """Exempting a word does not exempt a different pair; an exempted pair is honoured."""
    hashes = {digest("zebrafish"), digest("quokkamarsupial")}
    # Exempting the single word must not exempt the unrelated pair.
    only_word = frozenset({digest("zebrafish")})
    assert cft.line_hits("quokka marsupial", hashes, only_word)
    # An exempted digest that is itself a pair is honoured.
    pair = frozenset({digest("quokkamarsupial")})
    assert not cft.line_hits("quokka marsupial", hashes, pair)
    assert not cft.line_hits("Quokka_Marsupial", hashes, pair)
    # ...but does not exempt the other forbidden word.
    assert cft.line_hits("quokka marsupial zebrafish", hashes, pair)
    # Pair not forbidden-adjacent stays clean regardless.
    assert not cft.line_hits("quokka x marsupial", hashes)


def test_scan_text_exempt():
    """scan_text honours exempt digests per line and keeps default behaviour."""
    hashes = {digest("zebrafish"), digest("quokka")}
    exempt = frozenset({digest("zebrafish")})
    text = "zebrafish\nok\nquokka\nzebrafish quokka\n"
    assert cft.scan_text(text, hashes) == [1, 3, 4]
    assert cft.scan_text(text, hashes, exempt) == [3, 4]
    assert cft.scan_text(text, hashes, frozenset(hashes)) == []


def _repo(tmp_path):
    """Create a fake repo root with a docs/ subdirectory."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    return root


def test_exempt_for_exact_root_file(tmp_path):
    """The exact repo-root file gets the configured exemption."""
    root = _repo(tmp_path)
    f = root / EXEMPT_NAME
    f.write_text("x")
    assert cft.exempt_for(f, root) == cft.EXEMPTIONS[EXEMPT_NAME]


@pytest.mark.parametrize(
    "rel",
    ["README.md", "docs/TRADEMARKS.md", "trademarks.md", "Trademarks.md"],
)
def test_exempt_for_other_paths_empty(tmp_path, rel):
    """Other files, subdirectory copies and different case get no exemption."""
    root = _repo(tmp_path)
    f = root / rel
    f.write_text("x")
    assert cft.exempt_for(f, root) == frozenset()


def test_exempt_for_outside_repo(tmp_path):
    """A same-named file outside the repo root gets no exemption."""
    root = _repo(tmp_path)
    outside = tmp_path / EXEMPT_NAME
    outside.write_text("x")
    assert cft.exempt_for(outside, root) == frozenset()


def test_exempt_for_symlink_elsewhere(tmp_path):
    """A symlink named like the exempt file but pointing outside gets no exemption."""
    root = _repo(tmp_path)
    target = tmp_path / "elsewhere.md"
    target.write_text("x")
    link = root / EXEMPT_NAME
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported here")
    assert cft.exempt_for(link, root) == frozenset()


def test_main_outside_file_with_exempted_word_fails(tmp_path, monkeypatch, capsys):
    """An exempted word in a file that is not the repo's exempt file is still a hit."""
    hf = tmp_path / "h.txt"
    hf.write_text(digest("zebrafish"))
    monkeypatch.setattr(cft, "HASH_FILE", hf)
    monkeypatch.setattr(
        cft, "EXEMPTIONS", {EXEMPT_NAME: frozenset({digest("zebrafish")})}
    )
    other = tmp_path / "elsewhere"
    other.mkdir()
    for name in (EXEMPT_NAME, "notes.txt"):
        f = other / name
        f.write_text("zebrafish\n")
        assert cft.main([str(f)]) == 1
        assert ":1: forbidden term" in capsys.readouterr().out


def test_main_exit_codes_regression(tmp_path, monkeypatch):
    """main: 0 when clean, 1 on a hit, 2 when the hash file is missing."""
    hf = tmp_path / "h.txt"
    hf.write_text(digest("zebrafish"))
    monkeypatch.setattr(cft, "HASH_FILE", hf)
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing here")
    dirty = tmp_path / "dirty.txt"
    dirty.write_text("zebrafish")
    assert cft.main([str(clean)]) == 0
    assert cft.main([str(dirty)]) == 1
    monkeypatch.setattr(cft, "HASH_FILE", tmp_path / "missing.txt")
    assert cft.main([str(clean)]) == 2


def test_default_scan_covers_the_whole_repository(monkeypatch):
    """
    Regression (2026-10-19): the default scan listed only tools/, because it ran
    `git ls-files` with tools/ as its root, so every file elsewhere went unchecked.
    The default scan must cover tracked files outside tools/ too.
    """
    scanned = []
    monkeypatch.setattr(cft, "is_text_file", lambda path: scanned.append(path) or False)
    assert cft.main([]) == 0
    repo_root = cft.HASH_FILE.parent.parent.resolve()
    assert repo_root / "README.md" in scanned
    assert repo_root / "harness" / "shots" / "vm.py" in scanned
