# Pinned versions

The C++ effect API of the compositor is **not ABI-stable between versions**. The
whole build is therefore frozen to one snapshot of the Arch Linux Archive
(`ARCH_ARCHIVE_DATE` in `.env.example`) and every package version below follows
from that date. Changing the date is a task of its own, never a side effect of
other work: it needs a full `make verify-install` and a check that the compositor
effect still builds.

| Item | Value |
|---|---|
| Archive snapshot | 2026/09/24 |
| Recorded | 2026-09-25 |

Versions provided by that snapshot (read from the pinned mirror with `pacman -Si`):

| Package | Version |
|---|---|
| plasma-desktop | 6.7.5-1 |
| kwin | 6.7.5-1 |
| kvantum | 1.1.8-1 |
| sddm | 0.21.0-7 |
| dolphin | 26.08.1-1 |
| konsole | 26.08.1-1 |
| qt6-base | 6.11.2-3 |
| pipewire | 1:1.6.9-1 |
| mesa | 1:26.2.3-1 |
| linux | 7.2.6.arch2-1 |
| inter-font | 4.1-1 |
| ttf-jetbrains-mono | 2.304-2 |
