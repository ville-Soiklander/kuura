#!/bin/sh
# Sourced by the Plasma session at start-up (before KWin), see
# ~/.config/plasma-workspace/env/. Rendering settings for a guest WITHOUT a GPU.
#
# Mesa picks the software rasteriser (llvmpipe) through the kms_swrast driver when
# the KMS device is a plain virtual one; forcing it avoids a slow probe for a
# hardware driver that does not exist here and makes the choice explicit.
export LIBGL_ALWAYS_SOFTWARE=1
export MESA_LOADER_DRIVER_OVERRIDE=kms_swrast
