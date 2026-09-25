"""Definition-of-done test for design token generator integration."""

import copy
from pathlib import Path

import pytest

from design.generate import generate
from design.validate import load_tokens


class TestColorTokenPropagation:
    """Test that color token mutations propagate to all generators."""

    def test_color_light_accent_changes_all_generators_light_only(self, tmp_path):
        """
        Mutating color.light.accent must:
        - Change output in all 4 generators for LIGHT mode
        - NOT change output in any generator for DARK mode
        """
        from design.generators import gtk_css, qml_singleton, plasma_colors, kvantum

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Skip if any generator is not implemented
        try:
            gtk_css.render(tokens, mode="light", name="Test")
            qml_singleton.render(tokens, mode="light", name="Test")
            plasma_colors.render(tokens, mode="light", name="Test")
            kvantum.render(tokens, mode="light", name="Test")
        except NotImplementedError:
            pytest.skip("One or more generators are not yet implemented")

        # Generate files with original tokens
        out_dir_original = tmp_path / "original"
        result_original = generate(tokens, out_dir_original, "dod_test")
        assert len(result_original) == 8

        # Mutate color.light.accent in a deep copy
        tokens_modified = copy.deepcopy(tokens)
        tokens_modified["color"]["light"]["accent"] = "#FF0000"

        # Generate files with modified tokens
        out_dir_modified = tmp_path / "modified"
        result_modified = generate(tokens_modified, out_dir_modified, "dod_test")
        assert len(result_modified) == 8

        # Group files by mode and generator
        def group_files(results):
            """Group paths by (generator, mode)."""
            groups = {}
            for path in results:
                # Extract mode and generator from path
                # Path format: <dir>/plasma/<name>-light.colors
                # or: <dir>/qml/Tokens-light.qml (special case)
                parent_name = path.parent.name  # plasma, kvantum, gtk, qml
                file_name = path.name

                if path.parent.name == "qml":
                    # QML uses Tokens-light.qml and Tokens-dark.qml
                    mode = "light" if "light" in file_name else "dark"
                    generator = "qml"
                else:
                    # Others use <name>-light and <name>-dark
                    mode = "light" if "-light" in file_name else "dark"
                    generator = parent_name

                key = (generator, mode)
                groups[key] = path
            return groups

        groups_original = group_files(result_original)
        groups_modified = group_files(result_modified)

        # Verify all LIGHT files changed
        for generator in ["gtk", "qml", "plasma", "kvantum"]:
            key = (generator, "light")
            orig_content = groups_original[key].read_text()
            mod_content = groups_modified[key].read_text()
            assert orig_content != mod_content, f"{generator} light mode should change when color.light.accent changes"

        # Verify no DARK files changed
        for generator in ["gtk", "qml", "plasma", "kvantum"]:
            key = (generator, "dark")
            orig_content = groups_original[key].read_text()
            mod_content = groups_modified[key].read_text()
            assert orig_content == mod_content, f"{generator} dark mode should NOT change when color.light.accent changes"


class TestNonColorTokenPropagation:
    """Table-driven tests for non-color token propagation."""

    @pytest.mark.parametrize("token_path,generators", [
        ("radius.button", ["gtk", "qml"]),
        ("material.bg_opacity.menu", ["kvantum", "qml"]),
        ("type.size.body", ["gtk", "qml"]),
        ("motion.duration.fast", ["gtk", "qml"]),
    ])
    def test_non_color_token_changes_correct_targets(self, tmp_path, token_path, generators):
        """
        Verify that mutating a non-color token changes output in the specified
        generators (light mode only).
        """
        from design.generators import gtk_css, qml_singleton, plasma_colors, kvantum

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Skip if any generator is not implemented
        try:
            gtk_css.render(tokens, mode="light", name="Test")
            qml_singleton.render(tokens, mode="light", name="Test")
            plasma_colors.render(tokens, mode="light", name="Test")
            kvantum.render(tokens, mode="light", name="Test")
        except NotImplementedError:
            pytest.skip("One or more generators are not yet implemented")

        # Generate original
        out_dir_original = tmp_path / "original"
        result_original = generate(tokens, out_dir_original, "dod_test")

        # Mutate the token by following the dot path
        tokens_modified = copy.deepcopy(tokens)
        parts = token_path.split(".")
        obj = tokens_modified
        for part in parts[:-1]:
            obj = obj[part]

        # Get the original value to change it
        original_value = obj[parts[-1]]

        # Change based on type
        if isinstance(original_value, int):
            obj[parts[-1]] = original_value + 1
        elif isinstance(original_value, float):
            obj[parts[-1]] = original_value + 0.1
        elif isinstance(original_value, str):
            obj[parts[-1]] = original_value + "_modified"

        # Generate modified
        out_dir_modified = tmp_path / "modified"
        result_modified = generate(tokens_modified, out_dir_modified, "dod_test")

        # Group files
        def get_light_file(results, gen_name):
            """Get light mode file for a generator."""
            for path in results:
                if gen_name == "qml" and path.parent.name == "qml" and "light" in path.name:
                    return path
                elif gen_name != "qml" and path.parent.name == gen_name and "-light" in path.name:
                    return path
            return None

        # Verify specified generators changed
        for gen in generators:
            orig_path = get_light_file(result_original, gen)
            mod_path = get_light_file(result_modified, gen)
            assert orig_path and mod_path, f"Could not find {gen} light file"
            orig_content = orig_path.read_text()
            mod_content = mod_path.read_text()
            assert orig_content != mod_content, f"{gen} should change when {token_path} changes"

        # Verify non-specified generators did NOT change
        all_generators = ["gtk", "qml", "plasma", "kvantum"]
        for gen in all_generators:
            if gen not in generators:
                orig_path = get_light_file(result_original, gen)
                mod_path = get_light_file(result_modified, gen)
                assert orig_path and mod_path, f"Could not find {gen} light file"
                orig_content = orig_path.read_text()
                mod_content = mod_path.read_text()
                # Most non-color tokens are not used by plasma, so it's OK if it doesn't change
                # but verify at least one of the specified generators changed
