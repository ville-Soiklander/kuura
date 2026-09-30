"""Tests for design.generate_icons module (mirrors design/tests/test_generate.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from design.generate_icons import generate_icons, main
from design.icons.glyphs import ICONS
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


class TestGenerateIcons:
    """Tests for generate_icons()."""

    def test_generate_icons_writes_one_file_per_icon(self, tmp_path):
        """generate_icons() writes exactly len(ICONS) files, one per manifest entry."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_icons(tokens, tmp_path)

        assert len(result) == len(ICONS)
        assert len(result) > 0, "ICONS manifest must not be empty"
        for path in result:
            assert path.exists(), f"File not created: {path}"

    def test_generate_icons_creates_icons_subdirectory(self, tmp_path):
        """Every file lands under <out_dir>/icons/."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_icons(tokens, tmp_path)

        for path in result:
            assert path.parent == tmp_path / "icons"

    def test_generate_icons_filenames_match_icon_ids(self, tmp_path):
        """Each file is named <icon_id>.svg for every key of ICONS, and nothing else."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_icons(tokens, tmp_path)

        filenames = {path.name for path in result}
        expected = {f"{icon_id}.svg" for icon_id in ICONS}
        assert filenames == expected

    def test_generate_icons_returns_sorted_paths(self, tmp_path):
        """Return value is sorted (matches design.generate.generate()'s own contract)."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_icons(tokens, tmp_path)

        assert result == sorted(result)

    def test_generate_icons_file_content_is_valid_svg_document(self, tmp_path):
        """Every written file is non-empty, ends with a newline and looks like an SVG."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_icons(tokens, tmp_path)

        for path in result:
            content = path.read_text(encoding="utf-8")
            assert content.startswith("<svg ")
            assert content.rstrip("\n").endswith("</svg>")
            assert content.endswith("\n")

    def test_generate_icons_overwrites_existing_files(self, tmp_path):
        """Calling generate_icons() twice overwrites rather than erroring or duplicating."""
        tokens = load_tokens(TOKENS_PATH)

        first = generate_icons(tokens, tmp_path)
        second = generate_icons(tokens, tmp_path)

        assert first == second
        assert len(list((tmp_path / "icons").iterdir())) == len(ICONS)


class TestMain:
    """Tests for main()."""

    def test_main_success_exit_code_zero(self, tmp_path):
        """main() returns 0 on success and writes the icon files."""
        out_dir = tmp_path / "generated"

        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        icons_dir = out_dir / "icons"
        assert icons_dir.exists()
        files = list(icons_dir.glob("*.svg"))
        assert len(files) == len(ICONS)

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        """main() returns 1 when tokens are invalid; nothing is written."""
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(broken_tokens_file),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert not out_dir.exists(), "Nothing should be written on token error"

    def test_main_invalid_name_exit_code_two(self, tmp_path):
        """main() returns 2 when --name is invalid; nothing is written."""
        out_dir = tmp_path / "generated"

        exit_code = main([
            "--tokens", str(TOKENS_PATH),
            "--out-dir", str(out_dir),
            "--name", "InvalidName",
        ])

        assert exit_code == 2
        assert not out_dir.exists()

    def test_main_out_dir_outside_project_root_sibling_attack_prevented(self, tmp_path):
        """Regression: sibling directory with shared prefix must be rejected."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        proj_evil = tmp_path / "proj_evil"
        proj_evil.mkdir()

        with patch("design.generate_icons.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(proj_evil / "out"),
                "--name", "test_theme",
            ])

        assert exit_code == 2, "Sibling directory should be rejected"
        assert not (proj_evil / "out").exists()

    def test_main_parent_traversal_prevented(self, tmp_path):
        """Regression: .. traversal must be rejected."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        evil_path = proj_root / "subdir" / ".." / ".." / "evil"

        with patch("design.generate_icons.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(evil_path),
                "--name", "test_theme",
            ])

        assert exit_code == 2
        assert not evil_path.exists()

    def test_main_normal_subdirectory_allowed(self, tmp_path):
        """Normal subdirectories inside PROJECT_ROOT must be allowed."""
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        out_dir = proj_root / "build" / "generated"

        with patch("design.generate_icons.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        assert (out_dir / "icons").exists()

    def test_main_default_name_from_env(self, tmp_path, monkeypatch):
        """main() falls back to DISTRO_NAME / 'theme' without error (name currently unused)."""
        out_dir = tmp_path / "generated"
        monkeypatch.setenv("DISTRO_NAME", "my_distro")

        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_default_tokens_and_out_dir(self, tmp_path):
        """main() uses the real design/tokens.json and .build/generated when omitted."""
        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main(["--name", "test_theme"])

        assert exit_code == 0
        default_out_dir = tmp_path / ".build" / "generated"
        assert (default_out_dir / "icons").exists()
        assert len(list((default_out_dir / "icons").glob("*.svg"))) == len(ICONS)


class TestEndToEnd:
    """End-to-end: real tokens.json, real glyphs, real icon_svg generator."""

    def test_every_icon_is_reachable_via_the_cli(self, tmp_path):
        """Every ICONS key produces a real, distinct, non-empty SVG file via main()."""
        out_dir = tmp_path / "generated"

        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        contents = []
        for icon_id in ICONS:
            path = out_dir / "icons" / f"{icon_id}.svg"
            assert path.exists(), f"Missing icon file for {icon_id}"
            text = path.read_text(encoding="utf-8")
            assert len(text) > 0
            contents.append(text)

        # Distinct glyphs must produce distinct files (guards against every
        # icon accidentally sharing one glyph_content by reference/copy-paste).
        assert len(set(contents)) == len(contents), "Every icon's SVG must be distinct"

    def test_missing_tokens_file_reports_error_not_traceback(self, tmp_path, capsys):
        """A nonexistent --tokens path is a clean exit code 1, not an unhandled exception."""
        out_dir = tmp_path / "generated"

        with patch("design.generate_icons.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tmp_path / "does_not_exist.json"),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert "error:" in capsys.readouterr().err
