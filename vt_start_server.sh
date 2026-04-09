#!/usr/bin/env bash
set -euo pipefail
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" || true
cd ~/repos/moksha-warp
pkill -f 'python3 -m warp.protocol.compositor' 2>/dev/null || true
rm -f /tmp/moksha-warp-run.log
SDL_VIDEO_X11_FORCE_EGL=1 python3 -m warp.protocol.compositor 2>&1 | tee /tmp/moksha-warp-run.log
