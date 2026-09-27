#!/usr/bin/env bash
# make-sample-tree.sh - create the fixed sample folder tree of the guest user.
#
# WHY: the `files-window` state shows a file manager. What it shows must be the same on
# every boot and on every build, so the tree is created here, at image build time, with
# fixed names, fixed contents (hence fixed sizes) and FIXED MODIFICATION TIMES. Nothing
# in it depends on the build host or on the moment of the build.
#
# The folders are the ones the desktop's places panel points at (see user-dirs.dirs in
# the session skeleton). The Desktop folder is deliberately left EMPTY: the desktop
# shows its content as icons, and the `desktop-empty` state must stay empty.
#
# Usage: make-sample-tree.sh HOME_DIR OWNER
#   HOME_DIR  home directory of the desktop user (must exist, must be below /home)
#   OWNER     user (and group) name that owns the tree

set -euo pipefail

# All time stamps are UTC so that they do not depend on the time zone of the build.
export TZ=UTC

HOME_DIR=""     # validated home directory
OWNER=""        # validated owner name
# Every created path with its modification time, applied once at the end. Applying the
# times last matters: creating a file changes the modification time of its directory.
declare -a STAMPS=()

# die MESSAGE...  Error message on stderr and non-zero exit.
die() { printf 'make-sample-tree.sh: error: %s\n' "$*" >&2; exit 1; }

# validate_args ARGS...
# Checks the two arguments: the values end up in paths and in chown, so they are
# validated instead of trusted.
validate_args() {
    [ "$#" -eq 2 ] || die "usage: make-sample-tree.sh HOME_DIR OWNER"
    [[ "$1" =~ ^/home/[a-z_][a-z0-9_-]*$ ]] || die "HOME_DIR must look like /home/<user>"
    [[ "$2" =~ ^[a-z_][a-z0-9_-]*$ ]] || die "OWNER is not a valid user name"
    [ -d "$1" ] || die "HOME_DIR does not exist"
    HOME_DIR="$1"
    OWNER="$2"
}

# make_dir REL_PATH STAMP
# Creates a directory below the home directory and records its modification time.
#   REL_PATH  path relative to the home directory (no leading slash, no "..")
#   STAMP     modification time as 'YYYY-MM-DD HH:MM:SS' (UTC)
make_dir() {
    local rel="$1" stamp="$2"
    [[ "$rel" != /* && "$rel" != *..* ]] || die "unsafe path: $rel"
    mkdir -p -- "$HOME_DIR/$rel"
    STAMPS+=("$rel|$stamp")
}

# make_file REL_PATH STAMP
# Creates a file below the home directory from standard input and records its
# modification time. The parent directory must have been created with make_dir.
#   REL_PATH  path relative to the home directory
#   STAMP     modification time as 'YYYY-MM-DD HH:MM:SS' (UTC)
make_file() {
    local rel="$1" stamp="$2"
    [[ "$rel" != /* && "$rel" != *..* ]] || die "unsafe path: $rel"
    cat > "$HOME_DIR/$rel"
    STAMPS+=("$rel|$stamp")
}

# build_tree
# The content of the tree. Text only (no binary files), so that the whole tree is
# reviewable in a diff.
build_tree() {
    # The places of the desktop; Desktop stays empty (see the header).
    make_dir Desktop   '2026-02-02 08:00:00'
    make_dir Documents '2026-09-10 16:45:00'
    make_dir Downloads '2026-08-30 12:10:00'
    make_dir Music     '2026-05-18 19:25:00'
    make_dir Pictures  '2026-07-04 10:05:00'
    make_dir Videos    '2026-04-22 21:40:00'

    make_file Notes.txt '2026-09-01 09:15:00' <<'EOF'
Things to remember

- Call the printer service on Monday.
- Renew the library card.
- Water the plants every second day.
EOF

    make_file shopping-list.txt '2026-08-12 18:02:00' <<'EOF'
bread
oat milk
coffee beans
lemons
tomatoes
EOF

    make_dir  Documents/Letters '2026-06-03 11:30:00'
    make_dir  Documents/Projects '2026-09-05 14:20:00'
    make_file 'Documents/Annual report.txt' '2026-03-14 09:30:00' <<'EOF'
Annual report - summary

This year the team shipped four releases and closed 212 issues. Support requests
dropped by a fifth after the documentation was rewritten. The two largest open
topics are the migration of the build system and the accessibility review.

Goals for next year
1. Reduce the time from commit to release to under one day.
2. Finish the accessibility review of every window.
3. Publish the design guidelines for contributors.
EOF

    make_file 'Documents/Budget 2026.csv' '2026-01-20 15:05:00' <<'EOF'
category,planned,spent
hardware,1200,980
software,400,415
training,600,250
travel,900,1130
misc,150,60
EOF

    make_file 'Documents/Meeting notes.md' '2026-09-10 16:45:00' <<'EOF'
# Weekly meeting

## Agenda
- Status of the release
- Open questions about the icon set
- Planning for next week

## Decisions
- The release moves by two days.
- The icon review happens on Thursday.
EOF

    make_file 'Documents/Reading list.txt' '2025-11-08 20:12:00' <<'EOF'
The Design of Everyday Things
A Pattern Language
The Elements of Typographic Style
EOF

    make_file 'Documents/Letters/cover-letter.txt' '2026-06-03 11:30:00' <<'EOF'
Dear hiring team,

please find attached my application for the open position. I look forward to
hearing from you.

Kind regards
EOF

    make_file 'Documents/Projects/README.md' '2026-09-05 14:20:00' <<'EOF'
# Sample project

A small placeholder project used to fill this folder.
EOF

    make_file 'Documents/Projects/todo.txt' '2026-08-21 07:50:00' <<'EOF'
[x] set up the repository
[x] write the first draft
[ ] review the draft
[ ] publish
EOF

    make_file Downloads/setup-guide.html '2026-08-30 12:10:00' <<'EOF'
<!doctype html>
<html><head><meta charset="utf-8"><title>Setup guide</title></head>
<body><h1>Setup guide</h1><p>Step one: unpack. Step two: run.</p></body></html>
EOF

    # A larger file so that the size column shows more than one unit: 400 fixed lines.
    # Process substitution instead of a pipe: a pipe would run make_file in a subshell
    # and its entry in STAMPS would be lost.
    make_file Downloads/data-export.json '2026-07-27 13:33:00' < <(
        for i in $(seq 1 400); do
            printf '{"id": %d, "name": "item-%03d", "value": %d}\n' "$i" "$i" "$(( (i * 37) % 1000 ))"
        done
    )

    make_file Music/playlist.m3u '2026-05-18 19:25:00' <<'EOF'
#EXTM3U
#EXTINF:215,Morning Light
morning-light.ogg
#EXTINF:187,Evening Walk
evening-walk.ogg
EOF

    make_file Pictures/sketch.svg '2026-07-04 10:05:00' <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200" viewBox="0 0 320 200">
  <rect width="320" height="200" fill="#e8eef4"/>
  <circle cx="90" cy="100" r="50" fill="#3b7dd8"/>
  <rect x="160" y="55" width="110" height="90" rx="12" fill="#d8843b"/>
</svg>
EOF

    make_file Pictures/logo-draft.svg '2026-06-29 17:48:00' <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
  <rect width="200" height="200" fill="#ffffff"/>
  <path d="M40 160 L100 40 L160 160 Z" fill="#4c9a6a"/>
</svg>
EOF

    make_file Videos/clips.txt '2026-04-22 21:40:00' <<'EOF'
clip-01: intro, 00:42
clip-02: walkthrough, 03:15
EOF
}

# apply_stamps
# Applies every recorded modification time and hands the tree over to the desktop user.
# --no-dereference: a symbolic link must never be followed out of the tree.
apply_stamps() {
    local entry rel stamp
    for entry in "${STAMPS[@]}"; do
        rel="${entry%%|*}"
        stamp="${entry#*|}"
        touch --no-dereference --date="$stamp" -- "$HOME_DIR/$rel"
        chown --no-dereference "$OWNER:$OWNER" -- "$HOME_DIR/$rel"
    done
}

# main ARGS...
main() {
    validate_args "$@"
    build_tree
    apply_stamps
}

main "$@"
