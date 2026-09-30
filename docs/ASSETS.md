# Third-party assets

Every third-party asset that ships with or is pulled in by this project is listed
here **before** it is merged: source, license, URL and retrieval date.
Nothing in this project originates from any proprietary operating system vendor.

| Asset | Used for | Delivered as | License | Source | Retrieved |
|---|---|---|---|---|---|
| Inter (font family) | UI font, base of the project's own UI font alias | Arch package `inter-font`, pulled in by the metapackage | SIL Open Font License 1.1 | https://github.com/rsms/inter | 2026-09-25 |
| JetBrains Mono (font family) | Monospace font | Arch package `ttf-jetbrains-mono`, pulled in by the metapackage | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono | 2026-09-25 |
| Capitaine cursors (cursor theme) | Mouse cursor theme, a variant of KDE Breeze cursors styled after this project's own visual language | Arch package `capitaine-cursors`, pulled in by the metapackage | LGPL-3.0 (LGPLv3) | https://github.com/keeferrourke/capitaine-cursors | 2026-09-30 |

Notes:

- The fonts and cursor theme are installed from the distribution's package
  repositories at install time; their files are not stored in this repository.
- `breeze-cursors` (LGPL-2.0-or-later) is already present transitively via
  `kwin -> breeze -> breeze-cursors` regardless of the Capitaine entry above -
  Capitaine is chosen over it only for a distinct look fitting this project's
  own visual language, not to introduce a new class of license exposure this
  project did not already carry.
- The icon set (`design/icons/glyphs.py`, `design/generators/icon_svg.py`), the
  5 wallpaper compositions (`design/generate_wallpapers.py`) and the 8 UI
  sounds (`design/generate_sounds.py`) are this project's own procedural
  output, not third-party assets in the sense of this file's own scope - no
  entry needed here. Human sign-off (Vaihe 5's own DoD) was given 2026-09-30
  after visual/descriptive review of the generated output. Packaged by
  `packages/kuura-assets/PKGBUILD`, whose own SCOPE comment documents exactly
  which parts (icon-theme `index.theme`, sound-theme wiring) are installed at
  a minimal, not-yet-live-verified level.
