"""Tests for report and HTML rendering."""

from __future__ import annotations

from pathlib import Path

from harness.shots.review import render_report, render_review_html


def test_render_report_empty() -> None:
    """Render report with no results."""
    results = []
    report = render_report(results)
    assert "Mode" in report
    assert "Status" in report
    assert "Pixels" in report


def test_render_report_pass() -> None:
    """Render report with passing result."""
    results = [
        {
            "mode": "light",
            "state": "desktop-empty",
            "status": "pass",
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
            "bbox": None,
        },
    ]
    report = render_report(results)
    assert "light" in report
    assert "desktop-empty" in report
    assert "✓ pass" in report or "pass" in report


def test_render_report_fail() -> None:
    """Render report with failing result."""
    results = [
        {
            "mode": "dark",
            "state": "shelf-hover",
            "status": "fail",
            "differing_pixels": 100,
            "ratio": 0.0001,
            "max_delta": 15,
            "bbox": (100, 200, 150, 250),
        },
    ]
    report = render_report(results)
    assert "dark" in report
    assert "shelf-hover" in report
    assert "✗ fail" in report or "fail" in report
    assert "100" in report
    assert "15" in report


def test_render_report_missing_golden() -> None:
    """Render report with missing golden."""
    results = [
        {
            "mode": "light",
            "state": "new-state",
            "status": "missing-golden",
            "differing_pixels": None,
            "ratio": None,
            "max_delta": None,
            "bbox": None,
        },
    ]
    report = render_report(results)
    assert "light" in report
    assert "new-state" in report
    assert "missing" in report.lower()


def test_render_report_missing_shot() -> None:
    """Render report with missing shot."""
    results = [
        {
            "mode": "dark",
            "state": "old-state",
            "status": "missing-shot",
            "differing_pixels": None,
            "ratio": None,
            "max_delta": None,
            "bbox": None,
        },
    ]
    report = render_report(results)
    assert "dark" in report
    assert "old-state" in report
    assert "missing" in report.lower()


def test_render_report_html_escaping() -> None:
    """Test that HTML is properly escaped in report."""
    results = [
        {
            "mode": "light<script>",
            "state": "test&evil",
            "status": "pass",
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
            "bbox": None,
        },
    ]
    report = render_report(results)
    # Should be escaped to HTML entities
    assert "&lt;" in report or "light<script>" not in report
    assert "&amp;" in report or "test&evil" not in report


def test_render_review_html_empty(tmp_path: Path) -> None:
    """Render HTML review with no entries."""
    entries = []
    html = render_review_html(entries, tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "Screenshot Review" in html
    assert "</html>" in html


def test_render_review_html_pass(tmp_path: Path) -> None:
    """Render HTML review with passing entry."""
    entries = [
        {
            "mode": "light",
            "state": "desktop-empty",
            "status": "pass",
            "actual_path": "light/desktop-empty.png",
            "golden_path": "light/desktop-empty.png",
            "diff_path": None,
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
    ]
    html = render_review_html(entries, tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "light" in html
    assert "desktop-empty" in html
    assert "light/desktop-empty.png" in html
    assert "PASS" in html or "pass" in html


def test_render_review_html_fail_with_diff(tmp_path: Path) -> None:
    """Render HTML review with failing entry and diff."""
    entries = [
        {
            "mode": "dark",
            "state": "shelf-hover",
            "status": "fail",
            "actual_path": "dark/shelf-hover.png",
            "golden_path": "dark/shelf-hover.png",
            "diff_path": "dark/shelf-hover-diff.png",
            "differing_pixels": 50,
            "ratio": 0.00005,
            "max_delta": 20,
        },
    ]
    html = render_review_html(entries, tmp_path)
    assert "dark/shelf-hover.png" in html
    assert "dark/shelf-hover-diff.png" in html
    assert "FAIL" in html or "fail" in html


def test_render_review_html_missing_golden(tmp_path: Path) -> None:
    """Render HTML review with missing golden."""
    entries = [
        {
            "mode": "light",
            "state": "new-state",
            "status": "missing-golden",
            "actual_path": "light/new-state.png",
            "golden_path": None,
            "diff_path": None,
            "differing_pixels": None,
            "ratio": None,
            "max_delta": None,
        },
    ]
    html = render_review_html(entries, tmp_path)
    assert "light/new-state.png" in html
    assert "missing" in html.lower()


def test_render_review_html_missing_shot(tmp_path: Path) -> None:
    """Render HTML review with missing shot."""
    entries = [
        {
            "mode": "dark",
            "state": "removed-state",
            "status": "missing-shot",
            "actual_path": None,
            "golden_path": "dark/removed-state.png",
            "diff_path": None,
            "differing_pixels": None,
            "ratio": None,
            "max_delta": None,
        },
    ]
    html = render_review_html(entries, tmp_path)
    assert "dark/removed-state.png" in html
    assert "missing" in html.lower()


def test_render_review_html_no_external_resources() -> None:
    """Verify HTML is self-contained (no external resources)."""
    entries = [
        {
            "mode": "light",
            "state": "test",
            "status": "pass",
            "actual_path": "light/test.png",
            "golden_path": "light/test.png",
            "diff_path": None,
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
    ]
    html = render_review_html(entries, Path("/tmp"))

    # Should not reference external CDNs or resources
    assert "https://" not in html
    assert "http://" not in html
    # Should have inline style
    assert "<style>" in html
    assert "background-color:" in html


def test_render_review_html_relative_paths() -> None:
    """Verify relative paths are used in HTML."""
    entries = [
        {
            "mode": "light",
            "state": "test",
            "status": "pass",
            "actual_path": "light/test.png",
            "golden_path": "light/test.png",
            "diff_path": "light/test-diff.png",
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
    ]
    html = render_review_html(entries, Path("/tmp"))

    assert "light/test.png" in html
    assert "light/test-diff.png" in html
    assert "/tmp" not in html  # No absolute paths
    assert "C:" not in html  # No Windows drive letters


def test_render_review_html_html_escaping(tmp_path: Path) -> None:
    """Test HTML escaping in review."""
    entries = [
        {
            "mode": "light<script>",
            "state": "test&evil",
            "status": "pass",
            "actual_path": "light<script>/test&evil.png",
            "golden_path": "light<script>/test&evil.png",
            "diff_path": None,
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
    ]
    html = render_review_html(entries, tmp_path)

    # Paths should be escaped in src attributes
    assert "&lt;" in html or "light<script>" not in html
    assert "&amp;" in html or "test&evil" not in html


def test_render_review_html_light_dark_theme() -> None:
    """Test that HTML includes both light and dark mode CSS."""
    entries = []
    html = render_review_html(entries, Path("/tmp"))

    # Should have prefers-color-scheme media query
    assert "prefers-color-scheme" in html
    assert "dark" in html.lower()


def test_render_review_html_multiple_modes(tmp_path: Path) -> None:
    """Test HTML with multiple modes."""
    entries = [
        {
            "mode": "light",
            "state": "state1",
            "status": "pass",
            "actual_path": "light/state1.png",
            "golden_path": "light/state1.png",
            "diff_path": None,
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
        {
            "mode": "dark",
            "state": "state2",
            "status": "fail",
            "actual_path": "dark/state2.png",
            "golden_path": "dark/state2.png",
            "diff_path": "dark/state2-diff.png",
            "differing_pixels": 10,
            "ratio": 0.0001,
            "max_delta": 5,
        },
    ]
    html = render_review_html(entries, tmp_path)

    # Both modes should appear as section headers
    assert "light" in html
    assert "dark" in html
    # Both states should appear
    assert "state1" in html
    assert "state2" in html


def test_render_review_html_status_badges(tmp_path: Path) -> None:
    """Test that status badges appear in HTML."""
    entries = [
        {
            "mode": "light",
            "state": "pass-test",
            "status": "pass",
            "actual_path": "light/pass-test.png",
            "golden_path": "light/pass-test.png",
            "diff_path": None,
            "differing_pixels": 0,
            "ratio": 0.0,
            "max_delta": 0,
        },
        {
            "mode": "dark",
            "state": "fail-test",
            "status": "fail",
            "actual_path": "dark/fail-test.png",
            "golden_path": "dark/fail-test.png",
            "diff_path": "dark/fail-test-diff.png",
            "differing_pixels": 100,
            "ratio": 0.001,
            "max_delta": 50,
        },
    ]
    html = render_review_html(entries, tmp_path)

    # Should contain status badge classes
    assert "status-pass" in html or "PASS" in html
    assert "status-fail" in html or "FAIL" in html
