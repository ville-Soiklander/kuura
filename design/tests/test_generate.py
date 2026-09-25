"""Tests for design.generate module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from design.generate import generate, main


class TestGenerate:
    """Tests for generate() function."""

    def test_generate_writes_eight_files(self, tmp_path):
        """generate() should write exactly 8 files: 4 generators × 2 modes."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Mock the render functions to avoid NotImplementedError
        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"):
            result = generate(tokens, tmp_path, "test_theme")

        # Verify exactly 8 files were created
        assert len(result) == 8, f"Expected 8 files, got {len(result)}: {result}"

        # Verify all files exist
        for path in result:
            assert path.exists(), f"File not created: {path}"

        # Verify files are sorted
        assert result == sorted(result), "Return value must be sorted"

    def test_generate_creates_correct_directory_structure(self, tmp_path):
        """generate() should create files in plasma/, kvantum/, gtk/, qml/ subdirectories."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"):
            result = generate(tokens, tmp_path, "mytheme")

        # Verify directory structure
        dirs = set(p.parent.name for p in result)
        assert dirs == {"plasma", "kvantum", "gtk", "qml"}, f"Expected 4 directories, got {dirs}"

        # Verify filenames contain the theme name
        for path in result:
            assert "mytheme" in path.name or path.parent.name == "qml", f"Expected theme name in {path.name}"

    def test_generate_invalid_name_raises_valueerror(self, tmp_path):
        """generate() should raise ValueError for invalid theme names."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Valid names: lowercase letters, digits, underscore, hyphen
        invalid_names = [
            "Theme",  # uppercase
            "my theme",  # space
            "my-Theme",  # uppercase
            "my_theme!",  # invalid char
            "my.theme",  # dot
            "/theme",  # slash
        ]

        for invalid_name in invalid_names:
            with pytest.raises(ValueError, match="name.*lowercase"):
                generate(tokens, tmp_path, invalid_name)

    def test_generate_valid_names(self, tmp_path):
        """generate() should accept valid theme names."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        valid_names = [
            "theme",
            "my_theme",
            "my-theme",
            "theme123",
            "my_theme_123",
            "a",
            "z",
            "z123",
        ]

        for valid_name in valid_names:
            with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
                 patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
                 patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
                 patch("design.generators.kvantum.render", return_value="kvantum output\n"):
                result = generate(tokens, tmp_path, valid_name)
                assert len(result) == 8

    def test_generate_calls_all_four_generators(self, tmp_path):
        """generate() should call all four generator.render() functions."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        with patch("design.generators.gtk_css.render", return_value="gtk output\n") as mock_gtk, \
             patch("design.generators.qml_singleton.render", return_value="qml output\n") as mock_qml, \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n") as mock_plasma, \
             patch("design.generators.kvantum.render", return_value="kvantum output\n") as mock_kvantum:
            generate(tokens, tmp_path, "test_theme")

        # Verify each generator was called twice (light and dark)
        assert mock_gtk.call_count == 2, f"gtk_css.render called {mock_gtk.call_count} times, expected 2"
        assert mock_qml.call_count == 2, f"qml_singleton.render called {mock_qml.call_count} times, expected 2"
        assert mock_plasma.call_count == 2, f"plasma_colors.render called {mock_plasma.call_count} times, expected 2"
        assert mock_kvantum.call_count == 2, f"kvantum.render called {mock_kvantum.call_count} times, expected 2"

    def test_generate_returns_sorted_paths(self, tmp_path):
        """generate() should return sorted list of paths."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"):
            result = generate(tokens, tmp_path, "test_theme")

        # Verify sorted
        assert result == sorted(result), "Result must be sorted"


class TestMain:
    """Tests for main() function."""

    def test_main_success_exit_code_zero(self, tmp_path):
        """main() should return 0 on success."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        out_dir = tmp_path / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0, f"Expected exit code 0, got {exit_code}"

    def test_main_invalid_tokens_exit_code_one(self, tmp_path):
        """main() should return 1 when tokens are invalid."""
        broken_tokens_file = tmp_path / "broken.json"
        broken_tokens_file.write_text('{"invalid": "tokens"}')
        out_dir = tmp_path / "generated"

        with patch("design.generate.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(broken_tokens_file),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 1, f"Expected exit code 1 for invalid tokens, got {exit_code}"
        # Verify nothing was written
        assert not out_dir.exists(), "Nothing should be written on token error"

    def test_main_invalid_name_exit_code_two(self, tmp_path):
        """main() should return 2 when name is invalid."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        out_dir = tmp_path / "generated"

        exit_code = main([
            "--tokens", str(tokens_path),
            "--out-dir", str(out_dir),
            "--name", "InvalidName",  # uppercase not allowed
        ])

        assert exit_code == 2, f"Expected exit code 2 for invalid name, got {exit_code}"
        # Verify nothing was written
        assert not out_dir.exists(), "Nothing should be written on name error"

    def test_main_out_dir_outside_project_root_exit_code_two(self, tmp_path):
        """main() should return 2 when out-dir is outside PROJECT_ROOT."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        outside_dir = tmp_path.parent / "outside"

        # Monkeypatch PROJECT_ROOT to tmp_path to make outside_dir truly outside
        with patch("design.generate.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(outside_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 2, f"Expected exit code 2 for out-dir outside PROJECT_ROOT, got {exit_code}"
        # Verify nothing was written
        assert not outside_dir.exists(), "Nothing should be written on path error"

    def test_main_files_written_on_success(self, tmp_path):
        """main() should write files on success."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        out_dir = tmp_path / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        assert out_dir.exists(), "Output directory should be created"
        # Verify files were written (only count files, not directories)
        files = [p for p in out_dir.rglob("*") if p.is_file()]
        assert len(files) == 8, f"Expected 8 files, got {len(files)}: {files}"

    def test_main_default_tokens_path(self, tmp_path):
        """main() should use default tokens.json if not specified."""
        out_dir = tmp_path / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path), \
             patch("design.validate.load_tokens") as mock_load:
            mock_load.return_value = {
                "color": {"light": {}, "dark": {}},
                "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "test"},
                "material": {
                    "blur_radius": 36,
                    "noise": 0.02,
                    "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                    "edge_highlight": {"opacity": 0.28, "width": 1.0},
                    "inner_shadow": {"opacity": 0.10, "blur": 3},
                    "refraction": {"strength": 0.035, "edge_falloff": 12},
                },
                "spacing": {"grid": 4, "gutter": 12, "section": 20},
                "type": {
                    "family_ui": "Inter",
                    "family_mono": "JetBrains Mono",
                    "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                    "weight": {"regular": 400, "medium": 500, "semibold": 600},
                    "tracking": {"body": -0.01, "header": -0.02},
                },
                "motion": {
                    "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                    "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)",
                    "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
                },
                "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
            }
            exit_code = main([
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        # Verify load_tokens was called with the default path
        assert mock_load.called

    def test_main_default_out_dir(self, tmp_path):
        """main() should use default out-dir if not specified."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--name", "test_theme",
            ])

        assert exit_code == 0
        # Default out_dir should be .build/generated relative to PROJECT_ROOT
        default_out_dir = tmp_path / ".build" / "generated"
        assert default_out_dir.exists(), f"Default out-dir should be created at {default_out_dir}"

    def test_main_default_name_from_env(self, tmp_path):
        """main() should use DISTRO_NAME environment variable for default name."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        out_dir = tmp_path / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path), \
             patch.dict(os.environ, {"DISTRO_NAME": "my_distro"}):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_default_name_fallback(self, tmp_path):
        """main() should use 'theme' as fallback if DISTRO_NAME not set."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        out_dir = tmp_path / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", tmp_path), \
             patch.dict(os.environ, {}, clear=False) as env:
            # Ensure DISTRO_NAME is not set
            if "DISTRO_NAME" in env:
                del env["DISTRO_NAME"]
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(out_dir),
            ])

        assert exit_code == 0

    def test_main_sibling_directory_attack_prevented(self, tmp_path):
        """Regression: sibling directory with shared prefix must be rejected."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        # Create a directory structure like /tmp/proj and /tmp/proj_evil
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        proj_evil = tmp_path / "proj_evil"
        proj_evil.mkdir()

        # Monkeypatch PROJECT_ROOT to proj and try to write to proj_evil
        with patch("design.generate.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(proj_evil / "out"),
                "--name", "test_theme",
            ])

        assert exit_code == 2, "Sibling directory should be rejected"
        assert not (proj_evil / "out").exists(), "Nothing should be written for path traversal attempt"

    def test_main_parent_traversal_prevented(self, tmp_path):
        """Regression: .. traversal must be rejected."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        proj_root = tmp_path / "proj"
        proj_root.mkdir()

        # Try to traverse outside with ..
        evil_path = proj_root / "subdir" / ".." / ".." / "evil"

        with patch("design.generate.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(evil_path),
                "--name", "test_theme",
            ])

        assert exit_code == 2, "Parent traversal should be rejected"

    def test_main_normal_subdirectory_allowed(self, tmp_path):
        """Normal subdirectories inside PROJECT_ROOT must be allowed."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        proj_root = tmp_path / "proj"
        proj_root.mkdir()
        out_dir = proj_root / "build" / "generated"

        with patch("design.generators.gtk_css.render", return_value="gtk output\n"), \
             patch("design.generators.qml_singleton.render", return_value="qml output\n"), \
             patch("design.generators.plasma_colors.render", return_value="plasma output\n"), \
             patch("design.generators.kvantum.render", return_value="kvantum output\n"), \
             patch("design.generate.PROJECT_ROOT", proj_root):
            exit_code = main([
                "--tokens", str(tokens_path),
                "--out-dir", str(out_dir),
                "--name", "test_theme",
            ])

        assert exit_code == 0, "Normal subdirectory should be allowed"
        assert out_dir.exists(), "Output directory should be created"


class TestEndToEnd:
    """End-to-end tests using real generators (skip if they raise NotImplementedError)."""

    def test_generate_end_to_end_with_real_generators(self, tmp_path):
        """End-to-end test with real generators (skipped if any is not implemented)."""
        from design.validate import load_tokens
        from design.generators import gtk_css, qml_singleton, plasma_colors, kvantum

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Check if any generator still raises NotImplementedError
        try:
            gtk_css.render(tokens, mode="light", name="Test")
            qml_singleton.render(tokens, mode="light", name="Test")
            plasma_colors.render(tokens, mode="light", name="Test")
            kvantum.render(tokens, mode="light", name="Test")
        except NotImplementedError:
            pytest.skip("One or more generators are not yet implemented")

        # If all generators are implemented, run the end-to-end test
        result = generate(tokens, tmp_path, "e2e_theme")

        # Verify 8 files were created
        assert len(result) == 8
        for path in result:
            assert path.exists(), f"File not created: {path}"
            # Verify file is not empty and ends with newline
            content = path.read_text()
            assert len(content) > 0, f"File is empty: {path}"
            assert content.endswith("\n"), f"File does not end with newline: {path}"
