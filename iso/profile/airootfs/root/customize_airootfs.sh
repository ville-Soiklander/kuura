#!/usr/bin/env bash
# Live-session setup (docs/ISO_CONTRACT.md, "Live session"). mkarchiso runs this once,
# late in the ISO build, via `arch-chroot -N <pacstrap_dir> /root/customize_airootfs.sh`
# (confirmed from this exact pinned mkarchiso's own source, _make_customize_airootfs:
# it runs AFTER every package in packages.x86_64 is already installed, chmods this
# file +x itself first, then deletes it when done - upstream marks the mechanism
# deprecated but it is still fully functional in archiso 90-1, the version
# ARCH_ARCHIVE_DATE pins). Mirrors harness/vm/Containerfile's own, already-verified
# autologin mechanism as closely as the two environments allow: same useradd flags,
# same passwd --lock, same systemctl enable calls. Every golden screenshot in
# harness/goldens/ was captured through that Containerfile mechanism, which is why it
# is reused here rather than re-derived.
set -euo pipefail

# Fixed unprivileged live-session account, matching harness/vm/Containerfile's
# DESKTOP_USER pattern: video/render/input/audio give it access to the DRM, the GPU
# render node, input devices and audio. The password is locked, not merely unset, so
# there is no way to authenticate as this user other than SDDM's autologin
# (etc/sddm.conf.d/10-autologin.conf). "liveuser" is a generic session account name,
# not tied to any person or organisation.
useradd --create-home --user-group --groups video,render,input,audio --shell /bin/bash liveuser
passwd --lock liveuser

# Boot straight into the graphical target and start the display manager. `systemctl
# enable` only creates symlinks, so it works inside this not-yet-booted chroot with no
# running systemd - exactly as harness/vm/Containerfile's own identical two lines rely
# on.
systemctl set-default graphical.target
systemctl enable sddm.service
