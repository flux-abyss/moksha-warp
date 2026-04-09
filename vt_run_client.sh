#!/usr/bin/env bash
set -euo pipefail
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export WAYLAND_DISPLAY=wayland-warp
weston-simple-dmabuf-egl
