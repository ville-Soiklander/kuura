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
show it busy, but a synthetic full-host-load test (all host cores saturated by other
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
