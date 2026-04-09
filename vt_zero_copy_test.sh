#!/usr/bin/env bash
set -u

STAMP="$(date +%Y%m%d-%H%M%S)"
LOGDIR="$HOME/repos/moksha-warp/logs/proof"
RUNLOG="$LOGDIR/vt-zero-copy-$STAMP.log"
CLIENTLOG="$LOGDIR/vt-zero-copy-client-$STAMP.log"
SUMMARY="$LOGDIR/vt-zero-copy-summary-$STAMP.txt"

mkdir -p "$LOGDIR"

echo "moksha-warp vt-zero-copy test" | tee -a "$SUMMARY"
echo "stamp: $STAMP" | tee -a "$SUMMARY"

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true
export WAYLAND_DISPLAY=wayland-warp

cd "$HOME/repos/moksha-warp" || exit 1

pkill -f 'python3 -m warp.protocol.compositor' 2>/dev/null || true
rm -f /tmp/moksha-warp-run.log

echo "[1/4] starting compositor..." | tee -a "$SUMMARY"
SDL_VIDEO_X11_FORCE_EGL=1 python3 -m warp.protocol.compositor >"$RUNLOG" 2>&1 &
SERVER_PID=$!
sleep 2

echo "[2/4] starting dmabuf client..." | tee -a "$SUMMARY"
timeout 6s weston-simple-dmabuf-egl >"$CLIENTLOG" 2>&1 || true
sleep 1

echo "[3/4] summary:" | tee -a "$SUMMARY"
grep -nE '\[direct-scanout\]|\[scanout\]|\[gles\] flip done|drmModeSetCrtc|DMABUF IMPORT SUCCESS' "$RUNLOG" | tee -a "$SUMMARY" || true

echo "[4/4] file locations:" | tee -a "$SUMMARY"
echo "RUNLOG=$RUNLOG" | tee -a "$SUMMARY"
echo "CLIENTLOG=$CLIENTLOG" | tee -a "$SUMMARY"
echo "SUMMARY=$SUMMARY" | tee -a "$SUMMARY"

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
