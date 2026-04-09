#!/usr/bin/env bash
# Run the Python dma-buf test client against the moksha-warp server.
# The server must already be running (run_dmabuf_good.sh) before calling this.
set -e
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-warp
PYTHON=python3
if [ -f "$(dirname "$0")/.venv/bin/python3" ]; then
    PYTHON="$(dirname "$0")/.venv/bin/python3"
fi
exec "$PYTHON" scripts/dmabuf_test_client.py "$@"
