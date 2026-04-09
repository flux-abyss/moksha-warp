#!/usr/bin/env bash
# Run the moksha-warp dma-buf bridge server.
# Uses the .venv if present, otherwise falls back to system python3.
set -e
export XDG_RUNTIME_DIR=/run/user/1000
PYTHON=python3
if [ -f "$(dirname "$0")/.venv/bin/python3" ]; then
    PYTHON="$(dirname "$0")/.venv/bin/python3"
fi
SDL_VIDEO_X11_FORCE_EGL=1 "$PYTHON" -m warp.protocol.compositor "$@"
