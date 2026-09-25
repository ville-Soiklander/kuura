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

.PHONY: image repo verify-install check test clean require-config

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
