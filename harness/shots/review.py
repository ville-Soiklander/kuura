"""Report and HTML rendering for screenshot comparison results."""

from __future__ import annotations

import html
from pathlib import Path


def render_report(results: list[dict]) -> str:
    """
    Render a Markdown table of comparison results.

    Args:
        results: List of dicts with keys:
            - mode: color scheme (e.g., "light", "dark")
            - state: state name
            - status: "pass", "fail", "missing-golden", or "missing-shot"
            - differing_pixels: int or None
            - ratio: float or None (0.0-1.0)
            - max_delta: int or None
            - bbox: tuple (x0, y0, x1, y1) or None

    Returns:
        Markdown-formatted table.
    """
    lines = [
        "| Mode | State | Status | Pixels | Ratio | Max Δ | Bounding Box |",
        "|------|-------|--------|--------|-------|-------|--------------|",
    ]

    for result in results:
        mode = html.escape(result.get("mode", ""))
        state = html.escape(result.get("state", ""))
        status = result.get("status", "")

        # Status badge (plain text in Markdown)
        status_text = {
            "pass": "✓ pass",
            "fail": "✗ fail",
            "missing-golden": "⊘ missing golden",
            "missing-shot": "⊘ missing shot",
        }.get(status, status)

        differing = result.get("differing_pixels", "—")
        if isinstance(differing, int):
            ratio = result.get("ratio", 0.0)
            differing = f"{differing} ({100*ratio:.4f}%)"
        else:
            differing = "—"

        max_delta = result.get("max_delta")
        if max_delta is not None:
            max_delta = str(max_delta)
        else:
            max_delta = "—"

        bbox = result.get("bbox")
        if bbox:
            bbox_text = f"({bbox[0]}, {bbox[1]}) – ({bbox[2]}, {bbox[3]})"
        else:
            bbox_text = "—"

        lines.append(f"| {mode} | {state} | {status_text} | {differing} | | {max_delta} | {bbox_text} |")

    return "\n".join(lines)


def render_review_html(entries: list[dict], out_dir: Path) -> str:
    """
    Render a self-contained HTML review page.

    Generates one page with side-by-side new and golden images for every
    (mode, state) pair, plus diff images for failures. Uses relative image paths.

    Args:
        entries: List of dicts with keys:
            - mode: color scheme
            - state: state name
            - status: "pass", "fail", "missing-golden", or "missing-shot"
            - actual_path: relative path to actual image (or None if missing)
            - golden_path: relative path to golden image (or None if missing)
            - diff_path: relative path to diff image (only for failures, or None)

        out_dir: Output directory (used only to ensure relative paths are calculated correctly).

    Returns:
        HTML string (self-contained, no external resources, readable in light and dark).
    """
    # Group entries by mode for cleaner HTML structure
    by_mode = {}
    for entry in entries:
        mode = entry.get("mode", "unknown")
        if mode not in by_mode:
            by_mode[mode] = []
        by_mode[mode].append(entry)

    html_parts = [
        """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Screenshot Review</title>
    <style>
        :root {
            --bg: #ffffff;
            --fg: #000000;
            --border: #cccccc;
            --pass-bg: #e8f5e9;
            --fail-bg: #ffebee;
            --missing-bg: #fff3e0;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #1e1e1e;
                --fg: #e0e0e0;
                --border: #444444;
                --pass-bg: #1b5e20;
                --fail-bg: #b71c1c;
                --missing-bg: #e65100;
            }
        }
        body {
            font-family: system-ui, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--fg);
            margin: 0;
            padding: 20px;
        }
        h1 { margin-top: 0; }
        h2 { margin-top: 40px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
        .entry {
            margin-bottom: 40px;
            padding: 16px;
            border: 1px solid var(--border);
            border-radius: 4px;
        }
        .entry.pass { background-color: var(--pass-bg); }
        .entry.fail { background-color: var(--fail-bg); }
        .entry.missing { background-color: var(--missing-bg); }
        .entry-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .entry-title { font-weight: 600; font-size: 1.1em; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 3px;
            font-weight: 600;
            font-size: 0.9em;
        }
        .status-pass { background-color: #4caf50; color: white; }
        .status-fail { background-color: #f44336; color: white; }
        .status-missing { background-color: #ff9800; color: white; }
        .images-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        @media (max-width: 1024px) {
            .images-grid { grid-template-columns: 1fr; }
        }
        .image-box { text-align: center; }
        .image-box h4 { margin: 0 0 8px 0; font-size: 0.95em; }
        .image-box img {
            max-width: 100%;
            height: auto;
            border: 1px solid var(--border);
            border-radius: 3px;
        }
        .diff-image {
            grid-column: 1 / -1;
            text-align: center;
        }
        .diff-image img {
            max-width: 100%;
            height: auto;
            max-height: 600px;
            border: 1px solid var(--border);
            border-radius: 3px;
        }
        .metrics {
            font-size: 0.9em;
            color: var(--fg);
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <h1>Screenshot Review</h1>
""",
    ]

    # Render each mode section
    for mode in sorted(by_mode.keys()):
        html_parts.append(f"    <h2>{html.escape(mode)}</h2>\n")
        for entry in sorted(by_mode[mode], key=lambda e: e.get("state", "")):
            state = entry.get("state", "unknown")
            status = entry.get("status", "unknown")
            actual_path = entry.get("actual_path")
            golden_path = entry.get("golden_path")
            diff_path = entry.get("diff_path")
            differing_pixels = entry.get("differing_pixels")
            max_delta = entry.get("max_delta")
            ratio = entry.get("ratio")

            # Determine CSS class for styling
            status_class = (
                "pass"
                if status == "pass"
                else "fail" if status == "fail" else "missing"
            )
            status_badge = {
                "pass": "✓ PASS",
                "fail": "✗ FAIL",
                "missing-golden": "⊘ Missing Golden",
                "missing-shot": "⊘ Missing Shot",
            }.get(status, status.upper())

            html_parts.append(
                f"""    <div class="entry {status_class}">
        <div class="entry-header">
            <div class="entry-title">{html.escape(state)}</div>
            <span class="status-badge status-{status_class}">{status_badge}</span>
        </div>
        <div class="images-grid">
"""
            )

            # Actual image
            if actual_path:
                html_parts.append(
                    f"""            <div class="image-box">
                <h4>Actual</h4>
                <img src="{html.escape(actual_path)}" alt="Actual screenshot">
            </div>
"""
                )

            # Golden image
            if golden_path:
                html_parts.append(
                    f"""            <div class="image-box">
                <h4>Golden</h4>
                <img src="{html.escape(golden_path)}" alt="Golden screenshot">
            </div>
"""
                )

            # Diff image (if exists)
            if diff_path:
                metrics_text = ""
                if differing_pixels is not None:
                    metrics_text = f"Differing pixels: {differing_pixels}"
                    if ratio is not None:
                        metrics_text += f" ({100*ratio:.4f}%)"
                    if max_delta is not None:
                        metrics_text += f", Max Δ: {max_delta}"

                html_parts.append(
                    f"""            <div class="diff-image">
                <h4>Diff (red=differing, blue-tint=masked)</h4>
                <img src="{html.escape(diff_path)}" alt="Diff visualization">
                <div class="metrics">{html.escape(metrics_text)}</div>
            </div>
"""
                )

            html_parts.append("        </div>\n    </div>\n")

    html_parts.append(
        """</body>
</html>
"""
    )

    return "".join(html_parts)
