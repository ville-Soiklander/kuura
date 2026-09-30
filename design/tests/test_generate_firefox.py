"""Tests for design.generate_firefox module (mirrors design/tests/test_generate_icons.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from design.generate_firefox import generate_firefox, main
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


class TestGenerateFirefox:
    """Tests for generate_firefox()."""

    def test_writes_exactly_two_files(self, tmp_path):
        """userChrome.css and userContent.css, nothing else."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_firefox(tokens, tmp_path, "theme")

        assert len(result) == 2
        for path in result:
            assert path.exists()

    def test_files_land_under_firefox_chrome_subdirectory(self, tmp_path):
        """Both files land under <out_dir>/firefox/chrome/ - Firefox's own real profile path."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_firefox(tokens, tmp_path, "theme")

        for path in result:
            assert path.parent == tmp_path / "firefox" / "chrome"

    def test_filenames_are_the_real_firefox_names(self, tmp_path):
        """Firefox only loads files with these exact names from chrome/."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_firefox(tokens, tmp_path, "theme")

        filenames = {path.name for path in result}
        assert filenames == {"userChrome.css", "userContent.css"}

    def test_returns_sorted_paths(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)
        result = generate_firefox(tokens, tmp_path, "theme")
        assert result == sorted(result)

    def test_overwrites_existing_files(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)

        first = generate_firefox(tokens, tmp_path, "theme")
        second = generate_firefox(tokens, tmp_path, "theme")

        assert first == second
        assert len(list((tmp_path / "firefox" / "chrome").iterdir())) == 2


class TestMain:
    """Tests for main()."""

    def test_main_success_exit_code_zero(self, tmp_path):
        out_dir = tmp_path / "generated"

        with patch("design.generate_firefox.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        chrome_dir = out_dir / "firefox" / "chrome"
        assert (chrome_dir / "userChrome.css").exists()
        assert (chrome_dir / "userContent.css").exists()

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_firefox.PROJECT_ROOT", tmp_path):
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

        with patch("design.generate_firefox.PROJECT_ROOT", proj_root):
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

        with patch("design.generate_firefox.PROJECT_ROOT", proj_root):
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

        with patch("design.generate_firefox.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_default_tokens_and_out_dir(self, tmp_path):
        with patch("design.generate_firefox.PROJECT_ROOT", tmp_path):
            exit_code = main(["--name", "test_theme"])

        assert exit_code == 0
        default_out_dir = tmp_path / ".build" / "generated"
        assert (default_out_dir / "firefox" / "chrome" / "userChrome.css").exists()

    def test_missing_tokens_file_reports_error_not_traceback(self, tmp_path, capsys):
        out_dir = tmp_path / "generated"

        with patch("design.generate_firefox.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tmp_path / "does_not_exist.json"),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert "error:" in capsys.readouterr().err
