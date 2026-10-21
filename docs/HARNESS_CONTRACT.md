# Screenshot harness contract

Locked interface of the screenshot harness (phase V2). It gives every visual change a
mechanical verdict: the desktop is booted in a virtual machine, driven through named
states, photographed from the host, and compared with human-approved golden images.
Implementations must follow this document; change it deliberately and update every
implementation in the same change.

## Principles

- **Deterministic:** fixed resolution and scale, fixed clock, software rendering, no
  network, animations off while capturing, solid-colour wallpaper. Two runs from the
  same image and tokens must agree (see "Comparison").
- **Host-side capture:** screenshots come from QEMU (`screendump` over QMP), input goes
  in through QMP; the guest agent only starts programs and writes files. Nothing in the
  guest produces the picture.
- **Standard library only:** no image or diff dependency (PNG reading, writing and the
  comparison are implemented in `harness/shots/`).
- **Humans approve goldens:** no tool run by CI or by an agent may update a golden.
- **Own material only:** goldens are screenshots of this project's own build. Reference
  images of other systems never enter the repository, CI or an agent's context.

## Layout

```
harness/
  states.toml            state and mode definitions (schema below)
  vm/                    guest image: Containerfile, build_rootfs.sh, guest/ config
  shots/                 Python package `harness.shots`
    pngio.py diff.py review.py compare.py accept.py      (comparison side)
    qmp.py guest.py keys.py vm.py states.py runner.py capture.py determinism.py  (capture side)
    stock.py               stock Plasma "before" shots (see "Stock 'before' shots")
  goldens/<mode>/<state>.png     approved images, stored with git-lfs
```

Build outputs (git-ignored, under `.build/`): `vm/` (image, kernel, initramfs),
`shots/<mode>/<state>.png` + `shots/manifest.json`, `shots-diff/` (report and diffs).

## states.toml

```toml
[settings]
resolution = [2560, 1440]     # physical pixels; output scale is 2 (logical 1280x720)
settle_frames = 2             # consecutive identical frames that count as "stable"
settle_interval_s = 1.0
settle_timeout_s = 30
rtc_base = "2026-09-25T12:00:00"    # must be later than the archive snapshot date
reset = [ {key = "escape"}, {key = "escape"} ]   # steps run between states

[defaults]
tolerance = 3                 # per-channel difference (0..255) treated as equal
max_diff_ratio = 0.0005       # allowed fraction of differing pixels outside masks
mask = [[2300, 1340, 2560, 1440]]     # rectangles [x0, y0, x1, y1], physical pixels (panel clock)

[modes.light]
scheme = "light"              # colour scheme file  <name>-<scheme>.colors  from `python -m design.generate`
[modes.dark]
scheme = "dark"

[[state]]
name = "desktop-empty"        # unique, lowercase letters, digits and "-"
description = "..."           # one line
steps = []                    # see the step vocabulary
# optional per-state overrides: tolerance, max_diff_ratio, mask, modes = ["light"]
```

Step vocabulary (each step is an inline table with exactly one of these keys):

| Step | Meaning |
|---|---|
| `{ key = "meta+w" }` | key chord (`+` joins modifiers and one key) sent through QMP `input-send-event` |
| `{ type = "text" }` | types letters, digits and spaces as key events |
| `{ move = [x, y] }` / `{ click = [x, y] }` | absolute pointer move / left click, physical pixels |
| `{ run = ["cmd", "arg"] }` | start a program in the guest as the desktop user (session bus and Wayland variables set); does not wait for it to exit unless the step also has `wait_exit = true` |
| `{ wait = 1.5 }` | pause, seconds |
| `{ settle = true }` | wait until the screen is stable (settings above); a timeout is a failed state |

Modes are applied by writing the generated colour scheme file into the guest user's
colour scheme directory (through the guest agent) and activating it, so the image does
not depend on the tokens.

The states required by the working brief: `desktop-empty`, `menubar-open`,
`shelf-hover`, `overview`, `search-open`, `files-window`, `settings-window`,
`notification`, `browser-window`, each in `light` and `dark`. Until the bespoke
components exist, each state is defined with the stock component that plays its role
(for example the application launcher stands in for the menubar); the description says so.

`notification` is the one state in this list where no bespoke component is coming:
investigated and confirmed (2026-10-01, against the real plasma-workspace/libplasma
source pinned at this project's own KDE version, see `docs/VERSIONS.md`) that the
stock popup's text colour (`Kirigami.Theme`, the same mechanism the lock screen and
SDDM theme already rely on) and its frame/background (the Plasma Theme's shipped
`dialogs/background.svg`, which carries the standard `ColorScheme-*` stylesheet
classes every themed Plasma dialog uses) already follow the active colour scheme
with zero project code. The only other real, separate `plasmanotifyrc` levers
(popup position/timeout/do-not-disturb, confirmed via the real kcfg schemas) are
behavioural, not visual, and nothing in the working brief asks for a non-default
there. A bespoke visual override would mean shipping a whole custom Plasma Theme
SVG package re-skinning every Plasma dialog/tooltip/OSD session-wide, not just
notifications - clearly worse-scoped than what it would buy, so this is not planned.

## Commands

| Command | Behaviour |
|---|---|
| `python3 -m harness.shots.capture --out DIR [--states a,b] [--modes light,dark] [--name NAME] [--generated DIR] [--image-dir DIR]` | boot once, run every selected state in every selected mode, write `DIR/<mode>/<state>.png` and `DIR/manifest.json`. Exit 0 ok, 1 a state failed (did not settle, step failed), 2 environment problem (no KVM, image missing, bad states.toml). |
| `python3 -m harness.shots.compare --shots DIR --goldens DIR --out DIR [--allow-missing]` | per state: `pass`, `fail` or `missing-golden`; writes `summary.json`, `report.md`, `review.html` (new vs golden side by side) and `<mode>/<state>-diff.png` for failures. Exit 0 all pass (missing goldens allowed only with the flag), 1 any fail or missing, 2 environment problem. |
| `python3 -m harness.shots.accept --shots DIR --goldens DIR [--states a,b]` | copies shots into the golden tree. **Refuses (exit 2) when the environment variable `CI` is set.** |
| `python3 -m harness.shots.determinism --runs N ...` | runs `capture` N times (fresh boot each) and compares the runs with the state masks and tolerances; exit 0 only if all runs agree. |

Make targets: `vm-image` (build the guest image), `shots` (image, capture, compare with
goldens), `shots-determinism`, `goldens-review` (capture + compare with
`--allow-missing`, prints the path of `review.html`), `goldens-accept` (human only).

## Comparison

Perceptual metrics need heavy dependencies; the software-rendered guest is deterministic
enough for a tolerance based pixel comparison: a state passes when the number of pixels
whose largest channel difference exceeds `tolerance`, counted outside the masks, is at
most `max_diff_ratio` of all pixels. The panel clock is masked. Measured on the feasibility
spike: two clean boots differ in 32 of 3,686,400 pixels (max channel delta 3), all inside
the clock.

## Goldens

- Stored in `harness/goldens/<mode>/<state>.png` with git-lfs (`.gitattributes`).
- A new or changed golden needs a human decision: review `review.html`, then run
  `make goldens-accept` locally and commit.
- CI runs `make shots`; a missing or differing golden fails the job and uploads the
  diffs; on pull requests the summary is posted as a comment.

## GPU display mode (optional, local only)

`python3 -m harness.shots.capture --display gpu --out DIR ...` boots the same image with
`-device virtio-vga-gl` and `-display egl-headless,rendernode=/dev/dri/renderD128`
(virgl on the host GPU; under WSL2 that is the d3d12 render node). KWin then gets a
hardware GL context, so effects that need GL (Blur, Frost) render and can be screenshot-tested.

- **Default stays software.** Without `--display gpu` the QEMU command line is unchanged
  (legacy `VGA`, `-display none`); CI always uses it.
- **Capture goes over VNC.** QMP `screendump` fails ("no surface") while the guest scans out
  a GL texture, so gpu mode adds `-vnc unix:<run_dir>/vnc.sock` and `harness/shots/vnc.py`
  (stdlib RFB client, Raw encoding) takes each frame, ~0.3-1 s at 2560x1440. Input still
  goes through QMP. Every VNC operation has a timeout and an overall deadline, so a hung
  QEMU fails the run with an error instead of blocking.
- **Separate goldens.** Compare gpu captures only against `harness/goldens-gpu/`
  (`--goldens harness/goldens-gpu`); never mix them with `harness/goldens/`. Accepting
  gpu goldens is a human decision like any other. The first set (24 states) was accepted
  by the project owner on 2026-10-21; they are stored with git-lfs like `harness/goldens/`.
- **Deterministic only with a fixed noise pattern.** Frost's dither noise texture used a
  randomly seeded generator, so every compositor start drew a different pattern and two
  gpu runs of the same build differed by up to `material.noise` x 255 levels on every
  glass surface. Frost now seeds it with a constant (kuura-frost 0.1.0-8); two runs then
  match pixel for pixel in 23 of 24 states.
- **Fixed flake: first state's stale panels (2026-10-21).** The light `desktop-empty`
  state (the first capture after boot) sometimes failed with stock blue shelf and tray
  icons and a uniform fine difference over the whole top bar and shelf glass; a rerun
  passed. Cause: `plasma-apply-colorscheme` starts KWin's `blendchanges` effect, which
  crossfades from a snapshot of the old screen to the new one. When plasmashell
  recolours a panel while that crossfade runs, the panel is sometimes not repainted
  after it ends, and the screen keeps a stale picture of it (old icons and/or glass
  without the final tint) while nothing changes any more, so the settle rightly calls
  it stable. Evidence (gpu display, boot + light switch + `desktop-empty`, warm image):
  with the effect loaded 6 of 32 boots ended on a stale panel; the top bar healed only
  when its clock next ticked (20-35 s later), and one stale shelf stayed for over a
  minute through a KWin reconfigure, re-applying the scheme, a pointer move and opening
  the launcher. With the effect unloaded before the switch, 0 of 18 boots did. Fix:
  `Runner.apply_mode` unloads `blendchanges` over D-Bus (`org.kde.kwin.Effects`) before
  every switch and fails the mode if KWin still reports it loaded. The crossfade is a
  transition, never part of a captured state. The stale-panel bug itself is upstream
  (KWin/plasmashell) and can also hit a real user's desktop after a scheme switch.
- **Also fixed: a switch on a cold guest disk.** On a cold disk plasmashell can sit in
  uninterruptible disk sleep (icon lookups) for seconds between recolouring the panel
  background and the icons; the CPUs are idle meanwhile, and the probe used to count I/O
  wait as idle. Reproduced by dropping the guest page cache and throttling the virtual
  disk to 20 read IOPS (QMP `block_set_io_throttle`): the settle accepted the half-done
  frame, and the icons followed 8 s later. The guest CPU probe now reports I/O wait
  separately, and a poll is quiet only if at most 5 % of the CPU time was I/O wait (an
  idle desktop stays below 2 %; the blocked shell shows 25-30 % on 4 vCPUs) besides the
  15 % busy limit. This was a real gap but not the cause of the observed failures, which
  also happened on warm images.
- **Proves:** KWin runs with a GL context via virgl, and GL-dependent effects produce the
  expected pixels in that stack.
- **Cannot prove:** real-hardware performance; behaviour with the native NVIDIA, AMD or
  Intel drivers (the guest only sees virtio-gpu); anything in CI (no GPU there).
- **Host packages (Arch build distro):** `mesa`, `virglrenderer`, `qemu-hw-display-virtio-vga`,
  `qemu-hw-display-virtio-vga-gl`, `qemu-hw-display-virtio-gpu`, `qemu-hw-display-virtio-gpu-gl`,
  `qemu-ui-opengl`, `qemu-ui-egl-headless`. The render node must exist and be accessible.
- Note: software rendering in the normal mode comes from the emulated non-3D display
  device, not from `LIBGL_ALWAYS_SOFTWARE` (kwin_wayland on DRM ignores that variable).

## Stock "before" shots

`python3 -m harness.shots.stock [--out DIR] [--states a,b] [--display software|gpu] [--name NAME] [--image-dir DIR]`
(`harness/shots/stock.py`) photographs the SAME guest image with Plasma's own defaults, for
README before/after pairs. Output: `DIR/light/<state>.png` and `DIR/manifest.json`; the
default `DIR` is `.build/shots-stock` (or `.build/shots-stock-gpu` with `--display gpu`;
compare those with `harness/goldens-gpu/light`). Exit codes as `capture`. These pictures are
never goldens and are never compared or accepted.

One boot (with `-snapshot`, so the image never changes), then the product's per-user
settings are reverted at runtime as the desktop user, the result is read back, and only then
are states captured with the normal reset/steps/settle. What was product-specific was taken
from the image itself (package file lists of the product packages and the desktop user's
config), not guessed:

| Product setting (where it comes from) | Reverted to |
|---|---|
| `kdeglobals` `LookAndFeelPackage=<product>` (shell package skel) | `plasma-apply-lookandfeel --apply org.kde.breeze.desktop --resetLayout`: Breeze colours (Breeze Light), icons, widget style, Plasma theme, cursor, decoration, and the default layout (one bottom panel, default wallpaper) |
| Panel layout: top menubar with global menu + floating shelf (skel `plasma-org.kde.plasma.desktop-appletsrc`, `plasmashellrc` panel thickness/floating by containment id) | the look-and-feel's default layout; the old `[PlasmaViews][Panel 2/8]` keys are deleted first so a new panel cannot inherit them |
| `kwinrc` decoration plugin `<product>.decoration`, left button layout, `BorderSizeAuto`, `RoundedCorners` | keys deleted (KWin defaults); the look-and-feel sets `org.kde.breeze` |
| Glass compositor effect `<product>_frost` (installed "enabled by default") | `[Plugins] <product>_frostEnabled=false`, KWin reconfigured, effect unloaded |
| `kwinrc` `blendchangesEnabled=false`, Overview tuning, sliding-popup timing | keys deleted |
| `krunnerrc` `FreeFloating`, lock-screen wallpaper, Kvantum theme name, GTK theme names, `GTK_THEME`/`GTK_MODULES` session variables | deleted / unset (not visible in the offered states) |

The read-back must show: look-and-feel Breeze (or unset = default), colour scheme Breeze
Light (or unset), `breeze` icons, KWin's own support information naming `org.kde.breeze` as
the loaded decoration, the glass effect not loaded, exactly one panel, at the bottom, with
the stock applets and no global menu, and the `org.kde.image` wallpaper with the default
image. Any mismatch stops the run before a single state is captured (exit 2).

Not reverted on purpose (test infrastructure shared with the goldens, so the pair stays
comparable): the harness window rules, animation factor 0, cursor blink off, splash,
wallet, indexing and lock settings, the sample files. Also left alone because they are
inert or invisible: the product's installed-but-unselected themes, icons, sounds,
decoration plugin and colour schemes, the font alias file (only defines the product's
own family names, nothing selects them in a stock session), the login-screen theme (not
part of a running session), the welcome autostart (the test image keeps it off) and four
KWin shortcuts in `kglobalshortcutsrc` (no captured state uses them).

Offered states: `desktop-empty`, `files-window`, `settings-window`, `overview` (default
set), `search-open`, `notification`. Refused, with the reason in `EXCLUDED_STATES`:
`menubar-open` and `shelf-hover` (their pointer targets are the product's panels),
`app-menu-gtk` and `gtk4-widget-factory` (the image lacks the Breeze GTK theme a stock
Plasma install has, so GTK apps would look worse than stock), `browser-window` (the
product's preconfigured browser) and `welcome-window` (product-only program). Light mode
only.

- **Proves:** what this image's own Plasma 6 looks like with its defaults restored, same
  VM, programs, resolution, window geometry and sample content as the goldens.
- **Cannot prove:** that it equals a fresh stock install. Packages the product pulls in
  stay installed, a stock session started at first login would also run per-user
  migration/first-run steps that a runtime switch does not, KWin and plasmashell were
  started with the product config and switched live (not restarted), and the session
  variables of programs started by the harness come from a list read once per boot.
  Fonts, the wallpaper (the product does not change the desktop wallpaper) and the
  application set are the same on both sides, so the pair isolates the product's shell,
  decoration, colours and effects.

## Limits

**Confirmed empirically: standard GitHub-hosted `ubuntu-24.04` runners have no usable
`/dev/kvm`.** The `screenshot-harness` CI job checks for it and skips itself with a
warning rather than failing, so this is visible on every run rather than a silent gap.
Until the project has a KVM-capable runner (a self-hosted one, at the cost of the
security review that self-hosted runners need on a public repository, or a paid runner
tier GitHub documents as supporting nested virtualization), `make shots` and
`make shots-determinism` are validated locally only. `build-repo` (the signed package
repository and its installation) has no such gap and runs on every push.

Software rendering (llvmpipe) means GPU timing cannot be measured here; the frame-time
budget of the compositor effect is verified separately. The output scale configuration
is tied to the virtual monitor of a 2560x1440 mode.

**Determinism under host CPU contention is not guaranteed.** The settle logic (see
`harness/shots/runner.py`) already ignores a frame while the guest's own CPU counters
show it busy or waiting on its disk, but a synthetic full-host-load test (all host cores saturated by other
processes, well beyond ordinary CI contention) once produced large, unreproduced content
differences on `settings-window`, `browser-window` and `files-window` (up to 43% of the
screen) alongside a smaller, reproducible sensitivity on `menubar-open` (~0.4% of the
screen, inside the popup this state opens). A dedicated investigation instrumented the
guest's CPU accounting (including steal time, which `runner.py` deliberately excludes)
across roughly 600 measured settle polls under comparable and heavier synthetic load and
found no correlation between guest CPU state and the failures, and could not reproduce
the three large-diff cases at all despite genuine effort — so the mechanism is unresolved
and may have been a one-off. Run the harness on a host that is not itself under heavy
competing load; if a state fails intermittently only under real contention (a busy CI
runner, a shared machine), that is a known open risk, not a settle-logic bug to silently
retry past — capture the failing run's artifacts (`.build/shots-diff/`, the `.FAILED.png`
diagnostic) before re-running, so the next investigation has real data instead of a
second unreproduced anecdote.

## Reuse by the install harness (Vaihe 7)

`harness/install/` (`docs/ISO_CONTRACT.md`, "Installed-system verification") reuses
this document's own `Runner` + `states.toml` + comparison machinery unchanged to run
the same states/goldens against a real Calamares-installed system, reached by a
different, real-firmware boot path (`harness/install/boot.py`'s `InstallVm`, not this
document's own `Vm`) and a guest agent now also enabled on that installed target for
that reason (`packages/kuura-installer-config/calamares-defaults/modules/
services-systemd.conf`). Everything above about the comparison itself still applies
unchanged; see `docs/ISO_CONTRACT.md` for what is different about getting the guest
booted in the first place.
