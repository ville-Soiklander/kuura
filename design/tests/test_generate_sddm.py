"""Tests for design.generate_sddm module (mirrors design/tests/test_generate_firefox.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from design.generate_sddm import generate_sddm, main
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


class TestGenerateSddm:
    """Tests for generate_sddm()."""

    def test_writes_exactly_two_files(self, tmp_path):
        """Main.qml and theme.conf, nothing else."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_sddm(tokens, tmp_path, "theme")

        assert len(result) == 2
        for path in result:
            assert path.exists()

    def test_files_land_under_sddm_subdirectory(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)

        result = generate_sddm(tokens, tmp_path, "theme")

        for path in result:
            assert path.parent == tmp_path / "sddm"

    def test_filenames_are_the_real_sddm_names(self, tmp_path):
        """SDDM only loads a theme with these exact, fixed file names."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_sddm(tokens, tmp_path, "theme")

        filenames = {path.name for path in result}
        assert filenames == {"Main.qml", "theme.conf"}

    def test_returns_sorted_paths(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)
        result = generate_sddm(tokens, tmp_path, "theme")
        assert result == sorted(result)

    def test_overwrites_existing_files(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)

        first = generate_sddm(tokens, tmp_path, "theme")
        second = generate_sddm(tokens, tmp_path, "theme")

        assert first == second
        assert len(list((tmp_path / "sddm").iterdir())) == 2

    def test_pinned_to_dark_mode(self, tmp_path):
        """The greeter has no light/dark toggle - see module docstring for why."""
        tokens = load_tokens(TOKENS_PATH)

        generate_sddm(tokens, tmp_path, "theme")

        theme_conf = (tmp_path / "sddm" / "theme.conf").read_text(encoding="utf-8")
        assert f"background={_hex(tokens['color']['dark']['window'])}" in theme_conf


def _hex(value: str) -> str:
    """Lowercase 6-digit hex, matching design.generators.colors.to_hex_rgb()."""
    return value[:7].lower()


class TestMain:
    """Tests for main()."""

    def test_main_success_exit_code_zero(self, tmp_path):
        out_dir = tmp_path / "generated"

        with patch("design.generate_sddm.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        sddm_dir = out_dir / "sddm"
        assert (sddm_dir / "Main.qml").exists()
        assert (sddm_dir / "theme.conf").exists()

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_sddm.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(broken_tokens_file),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert not out_dir.exists(), "Nothing should be written on token error"

    def test_main_invalid_name_exit_code_two(self, tmp_path):
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

        with patch("design.generate_sddm.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(proj_evil / "out"),
                "--name", "test_theme",
            ])

        assert exit_code == 2, "Sibling directory should be rejected"
        assert not (proj_evil / "out").exists()

    def test_main_parent_traversal_prevented(self, tmp_path):
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        evil_path = proj_root / "subdir" / ".." / ".." / "evil"

        with patch("design.generate_sddm.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(evil_path),
                "--name", "test_theme",
            ])

        assert exit_code == 2
        assert not evil_path.exists()

    def test_main_default_name_from_env(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "generated"
        monkeypatch.setenv("DISTRO_NAME", "my_distro")

        with patch("design.generate_sddm.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_default_tokens_and_out_dir(self, tmp_path):
        with patch("design.generate_sddm.PROJECT_ROOT", tmp_path):
            exit_code = main(["--name", "test_theme"])

        assert exit_code == 0
        default_out_dir = tmp_path / ".build" / "generated"
        assert (default_out_dir / "sddm" / "Main.qml").exists()

    def test_missing_tokens_file_reports_error_not_traceback(self, tmp_path, capsys):
        out_dir = tmp_path / "generated"

        with patch("design.generate_sddm.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tmp_path / "does_not_exist.json"),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert "error:" in capsys.readouterr().err
