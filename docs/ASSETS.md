# Third-party assets

Every third-party asset that ships with or is pulled in by this project is listed
here **before** it is merged: source, license, URL and retrieval date.
Nothing in this project originates from any proprietary operating system vendor.

| Asset | Used for | Delivered as | License | Source | Retrieved |
|---|---|---|---|---|---|
| Inter (font family) | UI font, base of the project's own UI font alias | Arch package `inter-font`, pulled in by the metapackage | SIL Open Font License 1.1 (Arch package metadata: OFL-1.1-RFN, with Reserved Font Name; the font files are not modified, only aliased through fontconfig) | https://github.com/rsms/inter | 2026-09-25 |
| JetBrains Mono (font family) | Monospace font | Arch package `ttf-jetbrains-mono`, pulled in by the metapackage | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono | 2026-09-25 |
| Capitaine cursors (cursor theme) | Mouse cursor theme, a variant of KDE Breeze cursors styled after this project's own visual language | Arch package `capitaine-cursors`, pulled in by the metapackage | LGPL-3.0 (LGPLv3) | https://github.com/keeferrourke/capitaine-cursors | 2026-09-30 |
| Breeze icons (icon theme) | Fallback for every icon the project's own icon theme does not provide (`kuura-assets` sets `Inherits=breeze`); also pulled in by the Plasma session | Arch package `breeze-icons`, a dependency of `kuura-assets` | LGPL-2.1-only and LGPL-3.0-or-later | https://develop.kde.org/products/frameworks/ | 2026-10-19 |
| Ocean sound theme (event sounds) | Default Plasma event sounds; pulled in by `plasma-workspace`. The project's own 8 UI sounds do not replace it (see notes) | Arch package `ocean-sound-theme`, transitive via the metapackage | LGPL-2.0-or-later | https://kde.org/plasma-desktop/ | 2026-10-19 |
| Terminus Font (console bitmap font) | Console font of the live medium; not on the installer's removal list, so it also stays on the installed system | Arch package `terminus-font`, listed in `iso/profile/packages.x86_64` | GPL-2.0 (as declared by the Arch package) and SIL Open Font License 1.1 | http://terminus-font.sourceforge.net/ | 2026-10-19 |
| livecd-sounds (audio clips) | Audio prompts of the live session's accessibility helper; live medium only, removed from the installed system by the installer | Arch package `livecd-sounds`, listed in `iso/profile/packages.x86_64` | Creative Commons (Arch package metadata: `custom:CCPL`; exact CC variant not stated there, see Open) | https://alex19ep.me/public/ | 2026-10-19 |

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
  what is installed: an icon theme (including the "systray" glyph, under
  this project's own namespaced name, in the Icon Theme Specification's
  "Status" context - still with no first-party consumer) and both a flat
  plain-file sound install and a real freedesktop sound-theme-spec theme
  (event-name mapping, one approximated name) - and what, if anything,
  remains genuinely unverified rather than merely unclaimed.

Retrieval note for the rows dated 2026-10-19: the license and URL fields were
read from the Arch Linux package metadata (https://archlinux.org/packages/) on
that date, which describes the current repository version, not necessarily the
version in the pinned archive snapshot (`docs/VERSIONS.md`).

## Open

Items whose source or license could not be determined from the repository, for
the project owner to resolve before the first public release.

1. **Boot menu artwork on the BIOS path.** `iso/profile/syslinux/splash.png` is
   the artwork inherited from the upstream archiso reference profile and shows
   the Arch Linux logotype; the syslinux, GRUB and systemd-boot menu texts also
   still name "Arch Linux". The artwork is a third-party mark, is not listed
   above and its redistribution terms were not verified. It should be replaced
   with project-owned artwork (or removed), and the menu titles reviewed. The
   `iso/` directory was out of scope for this audit.
2. **Complete transitive audit.** Only visual, audio and font assets that are
   named in a `depends` array or in `iso/profile/packages.x86_64`, or that are
   direct dependencies of those, were audited. A full list needs the package
   manifest of a built ISO (`pkglist.x86_64.txt` inside the image); generate it
   and check it for font, icon, sound and wallpaper packages.
3. **Font provider chosen by pacman.** `plasma-desktop` requires the virtual
   `emoji-font` and `sddm` requires `ttf-font`; which concrete fonts pacman
   picks in the pinned snapshot (typically one of the Noto, DejaVu or Liberation
   families, all freely licensed) was not verified.
4. **Wallpapers and sounds from Plasma packages.** Whether the built ISO
   contains stock KDE wallpapers (`plasma-workspace-wallpapers`, LGPL) or the
   Oxygen sound theme (`oxygen-sounds`, LGPL-2.0-or-later) was not verified; they
   are not named in any `depends` array of this repository.
5. **livecd-sounds license variant.** The package metadata says only
   `custom:CCPL`; the exact Creative Commons variant and the author need to be
   read from the package's license file in the built image before release.
6. **Icon theme of GTK applications.** `gtk4-demos` and `mousepad` bring GTK
   and its default icon theme dependencies; the resulting package(s) and their
   licenses were not verified (see item 2).
