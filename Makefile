# Driver for the reproducible package build. The behaviour of every target is
# defined in docs/BUILD_CONTRACT.md; keep both in sync.
#
# Configuration is read from .env.example (documented defaults) and then from
# .env (local overrides, git-ignored), so values in .env win. A variable that is
# only set in the process environment is overridden by these files; pass it on the
# command line instead (make VAR=value), which beats everything.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

include .env.example
-include .env

# Surrounding whitespace in a value (easy to add by accident in .env) would end up
# in image names and URLs, so it is removed once here.
DISTRO_NAME       := $(strip $(DISTRO_NAME))
CONTAINER_ENGINE  := $(strip $(CONTAINER_ENGINE))
ARCH_ARCHIVE_DATE := $(strip $(ARCH_ARCHIVE_DATE))
REPO_DIR          := $(strip $(REPO_DIR))
GPG_KEY_ID        := $(strip $(GPG_KEY_ID))

# Recipes and the container refer to the configuration as $$VAR (never as an
# expanded Make value), so exporting is what carries it into the shell and,
# through `-e VAR`, into the build container.
export DISTRO_NAME CONTAINER_ENGINE ARCH_ARCHIVE_DATE REPO_DIR GPG_KEY_ID

IMAGE := localhost/$(DISTRO_NAME)-build

# Location of the finished repository inside the build container. It is the
# WORKDIR of build/Containerfile plus the output directory of build/build_repo.sh.
CONTAINER_REPO_DIR := /home/builder/repo

# Screenshot harness (docs/HARNESS_CONTRACT.md): where the generated theme files, the
# captured screenshots, the comparison report and the approved goldens live. The first
# three are build outputs below .build/ (git-ignored); the goldens are committed.
GENERATED_DIR  := .build/generated
SHOTS_DIR      := .build/shots
SHOTS_DIFF_DIR := .build/shots-diff
GOLDENS_DIR    := harness/goldens

.PHONY: image repo verify-install check test clean require-config \
	vm-image shots shots-determinism goldens-review goldens-accept

# Build the build image (packages frozen to ARCH_ARCHIVE_DATE, tools, user, scripts).
image: require-config
	$(CONTAINER_ENGINE) build \
		--build-arg ARCH_ARCHIVE_DATE="$$ARCH_ARCHIVE_DATE" \
		--tag "$(IMAGE)" \
		--file build/Containerfile \
		.

# Build and sign all packages in a fresh container and copy the repository out.
# The container is created, run and copied from as separate steps so that the
# result can be fetched after the build, and it is removed on every exit path
# (success, build failure or copy failure) by the EXIT trap.
repo: image
	@echo "==> building the repository in a container from $(IMAGE)"
	@cid="$$($(CONTAINER_ENGINE) create \
		-e DISTRO_NAME -e ARCH_ARCHIVE_DATE -e GPG_KEY_ID -e SOURCE_DATE_EPOCH \
		"$(IMAGE)" bash build/build_repo.sh)"; \
	trap '$(CONTAINER_ENGINE) rm --force "$$cid" >/dev/null 2>&1 || true' EXIT; \
	$(CONTAINER_ENGINE) start --attach "$$cid"; \
	rm -rf -- "$(REPO_DIR)"; \
	mkdir -p -- "$(REPO_DIR)"; \
	$(CONTAINER_ENGINE) cp "$$cid:$(CONTAINER_REPO_DIR)/." "$(REPO_DIR)/"; \
	echo "==> repository written to $(REPO_DIR)"

# Install the metapackage from the repository into a fresh container. The script
# is provided separately; this target only starts it after the repository exists.
verify-install: repo
	bash build/verify_install.sh

# Build the guest image of the screenshot harness (root.img, vmlinuz, initramfs.img in
# .build/vm/). It installs the metapackage from the signed repository, so the repository
# is rebuilt first; harness/vm/build_rootfs.sh keeps the expensive layers cached.
vm-image: repo
	bash harness/vm/build_rootfs.sh

# Boot the image, capture every state and compare the shots with the goldens. The
# theme files (colour schemes) that the capture applies inside the guest are generated
# from the design tokens first. Fails on any differing or missing golden.
shots: vm-image
	python3 -m design.generate --out-dir $(GENERATED_DIR)
	python3 -m harness.shots.capture --out $(SHOTS_DIR) --generated $(GENERATED_DIR)
	python3 -m harness.shots.compare --shots $(SHOTS_DIR) --goldens $(GOLDENS_DIR) --out $(SHOTS_DIFF_DIR)

# Boot and capture twice from a fresh boot each and check that the runs agree.
shots-determinism: vm-image
	python3 -m design.generate --out-dir $(GENERATED_DIR)
	python3 -m harness.shots.determinism --runs 2 --generated $(GENERATED_DIR)

# Capture and compare like `shots`, but tolerate states that have no golden yet, and
# print where the side-by-side report is. A state that differs from its golden is what a
# review is for, so exit status 1 of the comparison does not fail this target; status 2
# (a problem with the environment) does.
goldens-review: vm-image
	python3 -m design.generate --out-dir $(GENERATED_DIR)
	python3 -m harness.shots.capture --out $(SHOTS_DIR) --generated $(GENERATED_DIR)
	@status=0; \
	python3 -m harness.shots.compare --shots $(SHOTS_DIR) --goldens $(GOLDENS_DIR) --out $(SHOTS_DIFF_DIR) --allow-missing || status=$$?; \
	echo "review report: $(SHOTS_DIFF_DIR)/review.html"; \
	[ "$$status" -le 1 ] || exit "$$status"

# Accept the captured shots as the new goldens. A human decision: run it only after
# reading the review report, then commit the result. The tool refuses to run in CI.
goldens-accept:
	python3 -m harness.shots.accept --shots $(SHOTS_DIR) --goldens $(GOLDENS_DIR)

# Static checks that do not need a container.
check:
	python3 tools/check_forbidden_terms.py
	ruff check .

test:
	python3 -m pytest

# Remove build outputs and the build image. A missing image is not an error.
clean: require-config
	rm -rf -- .build
	@if $(CONTAINER_ENGINE) image inspect "$(IMAGE)" >/dev/null 2>&1; then \
		$(CONTAINER_ENGINE) rmi --force "$(IMAGE)"; \
	fi

# Fail early, with a readable message, when the configuration cannot work.
# Values are validated because they end up in image names, URLs and in an rm -rf
# (REPO_DIR); the checks mirror those in build/build_repo.sh.
require-config:
	@[ -n "$$DISTRO_NAME" ] || { echo "error: DISTRO_NAME is empty; set it in .env or .env.example" >&2; exit 1; }
	@[ -n "$$ARCH_ARCHIVE_DATE" ] || { echo "error: ARCH_ARCHIVE_DATE is empty; set it in .env or .env.example" >&2; exit 1; }
	@[ -n "$$CONTAINER_ENGINE" ] || { echo "error: CONTAINER_ENGINE is empty; use podman or docker" >&2; exit 1; }
	@[ -n "$$REPO_DIR" ] || { echo "error: REPO_DIR is empty; set it in .env or .env.example" >&2; exit 1; }
	@[[ "$$DISTRO_NAME" =~ ^[a-z0-9][a-z0-9_-]*$$ ]] || { echo "error: DISTRO_NAME may only contain lowercase letters, digits, '_' and '-'" >&2; exit 1; }
	@[[ "$$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$$ ]] || { echo "error: ARCH_ARCHIVE_DATE must have the form YYYY/MM/DD" >&2; exit 1; }
	@case "$$REPO_DIR" in \
		.|..|/*|../*|*/..|*/../*) echo "error: REPO_DIR must be a relative path inside the project" >&2; exit 1 ;; \
	esac
