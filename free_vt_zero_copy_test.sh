#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" || true

cd ~/repos/moksha-warp

pkill -f 'python3 -m warp.protocol.compositor' 2>/dev/null || true
rm -f /tmp/moksha-warp-run.log

echo
echo "Terminal 1: start compositor"
echo "Run this in one VT shell:"
echo "cd ~/repos/moksha-warp && SDL_VIDEO_X11_FORCE_EGL=1 python3 -m warp.protocol.compositor 2>&1 | tee /tmp/moksha-warp-run.log"
echo
echo "Terminal 2: run client"
echo "Run this in a second VT shell:"
echo "export XDG_RUNTIME_DIR=/run/user/\$(id -u)"
echo "export WAYLAND_DISPLAY=wayland-warp"
echo "weston-simple-dmabuf-egl"
echo
echo "After client runs: check result"
echo "grep -nE '\\[direct-scanout\\]|\\[scanout\\]|\\[gles\\] flip done' /tmp/moksha-warp-run.log"
echo
