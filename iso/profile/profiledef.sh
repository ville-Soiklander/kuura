#!/usr/bin/env bash
# shellcheck disable=SC2034
#
# Based on upstream archiso's own configs/releng/profiledef.sh (archiso 90-1, the
# version pinned by ARCH_ARCHIVE_DATE - see docs/ISO_CONTRACT.md). Changes from
# upstream are limited to this file's identity fields: iso_name/iso_label/iso_version
# (and, for the same "never hard code a name that is actually configuration" reason,
# iso_publisher/iso_application) now derive from DISTRO_NAME and SOURCE_DATE_EPOCH,
# both exported by the Makefile/iso/build_iso.sh exactly like every other build in
# this project (see build/build_repo.sh's set_source_date_epoch for the same
# derivation when SOURCE_DATE_EPOCH is not already set). DISTRO_NAME must already be
# validated (^[a-z0-9][a-z0-9_-]*$, see Makefile's require-config) before this runs.
: "${DISTRO_NAME:?DISTRO_NAME must be set}"

iso_name="${DISTRO_NAME}"
iso_label="${DISTRO_NAME^^}_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="${DISTRO_NAME}"
iso_application="${DISTRO_NAME} Live/Rescue"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86,arm64' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/root/.gnupg"]="0:0:700"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/Installation_guide"]="0:0:755"
  ["/usr/local/bin/livecd-sound"]="0:0:755"
)
