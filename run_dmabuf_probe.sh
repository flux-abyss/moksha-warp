#!/usr/bin/env bash
set -euo pipefail

CLIENT_CMD="${*:-weston-simple-dmabuf-egl}"
LOG=/tmp/moksha-warp-run.log

echo "== moksha-warp dmabuf probe =="
echo "client: $CLIENT_CMD"

rm -f "$LOG"

python3 -m warp.protocol.compositor >"$LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 1

export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-warp

echo
echo "== running client =="
bash -lc "$CLIENT_CMD" || true

sleep 1

echo
echo "== dmabuf signals =="
grep -nE 'linux_dmabuf_bind|zwp_linux_dmabuf_v1.destroy|zwp_linux_dmabuf_v1.create_params|create_immed|zwp_linux_buffer_params_v1|DMABUF IMPORT|created sent|failed sent|\\[renderer\\] dmabuf|wl_buffer.release' "$LOG" || true

echo
echo "== shm signals =="
grep -nE 'shm_bind|shm.create_pool|MyShmPoolResource.create_buffer|\\[renderer\\] shm|presented buffer' "$LOG" || true

echo
echo "== surface lifecycle =="
grep -nE 'wl_surface.attach|wl_surface.commit|sending wl_buffer.release|wl_buffer.release failed|present_buffer failed' "$LOG" || true

echo
echo "== full log path =="
echo "$LOG"
