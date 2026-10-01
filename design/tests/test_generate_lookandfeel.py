"""Tests for design.generate_lookandfeel module (mirrors design/tests/test_generate_sddm.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from design.generate_lookandfeel import generate_lookandfeel, main
from design.validate import load_tokens

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


class TestGenerateLookandfeel:
    """Tests for generate_lookandfeel()."""

    def test_writes_exactly_two_files(self, tmp_path):
        """metadata.json and Logout.qml, nothing else."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_lookandfeel(tokens, tmp_path, "theme")

        assert len(result) == 2
        for path in result:
            assert path.exists()

    def test_real_on_disk_layout(self, tmp_path):
        """metadata.json at the package root, Logout.qml nested under
        contents/logout/ - the real, fixed KPackage layout (module
        docstring), so packages/kuura-lookandfeel/'s own PKGBUILD can install
        every file unmodified."""
        tokens = load_tokens(TOKENS_PATH)

        result = generate_lookandfeel(tokens, tmp_path, "theme")

        lookandfeel_dir = tmp_path / "lookandfeel"
        assert (lookandfeel_dir / "metadata.json") in result
        assert (lookandfeel_dir / "contents" / "logout" / "Logout.qml") in result

    def test_returns_sorted_paths(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)
        result = generate_lookandfeel(tokens, tmp_path, "theme")
        assert result == sorted(result)

    def test_overwrites_existing_files(self, tmp_path):
        tokens = load_tokens(TOKENS_PATH)

        first = generate_lookandfeel(tokens, tmp_path, "theme")
        second = generate_lookandfeel(tokens, tmp_path, "theme")

        assert first == second

    def test_pinned_to_dark_mode(self, tmp_path):
        """The dialog has no light/dark toggle - see module docstring for why."""
        tokens = load_tokens(TOKENS_PATH)

        generate_lookandfeel(tokens, tmp_path, "theme")

        logout_qml = (tmp_path / "lookandfeel" / "contents" / "logout" / "Logout.qml").read_text(encoding="utf-8")
        # tokens.color.dark.window, formatted the QML way (design.generators.colors.to_qml) -
        # an opaque colour renders as uppercase "#RRGGBB".
        assert tokens["color"]["dark"]["window"][:7].upper() in logout_qml

    def test_name_feeds_metadata_but_not_package_id(self, tmp_path):
        """render_metadata_json()'s own real contract (module docstring,
        point 5): `name` reaches KPlugin.Name, never KPlugin.Id."""
        tokens = load_tokens(TOKENS_PATH)

        generate_lookandfeel(tokens, tmp_path, "my-distro-name")

        metadata = json.loads((tmp_path / "lookandfeel" / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["KPlugin"]["Name"] == "my-distro-name"
        assert metadata["KPlugin"]["Id"] == "kuura"


class TestMain:
    """Tests for main()."""

    def test_main_success_exit_code_zero(self, tmp_path):
        out_dir = tmp_path / "generated"

        with patch("design.generate_lookandfeel.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        lookandfeel_dir = out_dir / "lookandfeel"
        assert (lookandfeel_dir / "metadata.json").exists()
        assert (lookandfeel_dir / "contents" / "logout" / "Logout.qml").exists()

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate_lookandfeel.PROJECT_ROOT", tmp_path):
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

        with patch("design.generate_lookandfeel.PROJECT_ROOT", proj_root):
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

        with patch("design.generate_lookandfeel.PROJECT_ROOT", proj_root):
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

        with patch("design.generate_lookandfeel.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(TOKENS_PATH),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_default_tokens_and_out_dir(self, tmp_path):
        with patch("design.generate_lookandfeel.PROJECT_ROOT", tmp_path):
            exit_code = main(["--name", "test_theme"])

        assert exit_code == 0
        default_out_dir = tmp_path / ".build" / "generated"
        assert (default_out_dir / "lookandfeel" / "metadata.json").exists()

    def test_missing_tokens_file_reports_error_not_traceback(self, tmp_path, capsys):
        out_dir = tmp_path / "generated"

        with patch("design.generate_lookandfeel.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tmp_path / "does_not_exist.json"),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1
        assert "error:" in capsys.readouterr().err
