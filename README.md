# moksha-warp

Experimental Wayland compositor bridge for [Moksha](https://www.bodhilinux.com/) on Bodhi Linux.  
Written in Python. Runs inside an X11 session, hosting a private Wayland socket.

Real Wayland clients connect, negotiate surfaces and buffers, and get GPU-native
frames presented via EGLImage -> GL texture -> SDL preview window. No CPU copies
in the dma-buf path. Not a production compositor.

---

## What Currently Works

| Feature | Status |
|---------|--------|
| Private Wayland socket | yes |
| Real client connections | yes |
| XDG shell (wl_surface, xdg_toplevel) | yes |
| SHM buffer path (wl_shm) | yes |
| dma-buf protocol (zwp_linux_dmabuf_v1) | yes |
| EGLImage import from dma-buf | yes |
| GL texture bind -> textured quad draw | yes |
| Preview window present (SDL/GLES) | yes |
| wl_buffer.release lifecycle | yes |
| Frame callback delivery (wl_callback) | yes |
| Resource cleanup on surface destroy | yes |
| Clean shutdown (display.destroy, EGL, SDL) | yes |
| KMS device/connector/CRTC discovery | yes |
| Scanout eligibility classification | yes (detection only) |

---

## What Is Not Done Yet

- Direct scanout / KMS pageflip: classification works, actual pageflip
  not implemented. All clients currently render through the GLES preview path.
- Overlay plane presentation: `PLANE_CANDIDATE` buffers fall back to GLES,
  no hardware plane assignment yet.
- Production compositor behavior: no input forwarding, no focus management,
  no window decorations, no multi-output.
- Broad app compatibility: tested primarily with `weston-simple-dmabuf-egl`
  and `weston-simple-shm`. Other clients may hit unimplemented protocol paths.
- Stability: the runtime is validated but not hardened for edge cases like
  rapid client reconnects, exotic formats, or multi-plane dmabufs.

---

## Current Status

`weston-simple-dmabuf-egl` connects, negotiates dma-buf buffers, and renders
continuously. The compositor imports each frame as an EGLImage, binds it to a
GL texture, draws a fullscreen quad, and flips. Buffer release, frame callbacks,
and surface destroy all work. Shutdown is clean.

KMS scanout classification runs on every commit (`PRIMARY_SCANOUT_ELIGIBLE` /
`PLANE_CANDIDATE` / `BLOCKED`) based on real DRM connector mode discovery.
The `drmModeSetCrtc` call is not yet wired up, everything still goes through
the GLES preview window.

---

## Prerequisites

- Bodhi Linux 7 (Ubuntu base, initial development) or Bodhi Trixie (Debian 13 base, current)
- Python 3.10+
- `XDG_RUNTIME_DIR` set (e.g. `/run/user/1000`)
- A working `.venv` with dependencies installed:

```bash
python3 -m venv .venv
.venv/bin/pip install pywayland pygame
```

- For dma-buf path: `SDL_VIDEO_X11_FORCE_EGL=1` must be set (SDL/EGL conflict)
- For KMS probing: `libdrm` accessible at runtime

---

## Running

```bash
# Start the compositor
bash run_dmabuf_good.sh
```

Uses `.venv/bin/python3` if present, falls back to system Python.  
Sets `XDG_RUNTIME_DIR` and `SDL_VIDEO_X11_FORCE_EGL=1`.

```bash
# Connect the Python test client (second terminal)
bash run_test_client.sh

# Or connect weston's dmabuf client directly
WAYLAND_DISPLAY=wayland-warp XDG_RUNTIME_DIR=/run/user/1000 weston-simple-dmabuf-egl

# Compositor + client + log scan in one shot
bash run_dmabuf_probe.sh [optional-client-command]
```

---

## Package Layout

```text
warp/
  __init__.py
  protocol/
    compositor.py         # Wayland server: socket, globals, surface/buffer lifecycle
    __init__.py
  gpu/
    egl_import.py         # dma-buf -> EGLImage import path
    gles_renderer.py      # EGLImage -> GL texture -> draw -> swap
    __init__.py
  output/
    kms.py                # KMS probing, connector/mode discovery, scanout classification
    __init__.py
  render/
    __init__.py           # reserved / placeholder

scripts/
  dmabuf_test_client.py   # Python dma-buf Wayland client for local testing
  dmabuf_gl_probe.py      # GL/EGL capability probe
  wayland_globals_probe.py # standalone compositor probe (historical)
  evas_probe.py, ...      # earlier EFL/Evas investigation scripts

docs/
  00-goal.md
  01-environment.md
  02-current-status.md
  03-python-efl-findings.md
  04-wayland-probe-result.md
  05-client-handshake-result.md
  06-shm-progress.md
  07-shm-pool-breakthrough.md
  08-xdg-breakthrough.md
  09-night-one-status.md
  10-render-loop-breakthrough.md
  11-first-visible-frame.md
  12-dmabuf-zero-copy-path-confirmed.md
  13-dmabuf-import-success.md
  14-dmabuf-acceptance-and-release-loop.md
  15-dmabuf-buffer-creation-and-attach.md
  project_documentation.md
  # milestone notes, investigation logs, and project writeups

logs/
  proof/
    *-summary.txt         # curated run summaries (tracked)
    *.log                 # raw verbose output (typically gitignored)

archive/
  snapshots/              # pre-edit source snapshots
  backups/                # manual backup files
  legacy_scripts/         # retired shim/probe scripts
  combined_raw_session_dump.md  # raw combined session log
```

---

## Known Limitations

- **Preview ≠ scanout.** The GLES preview window is SDL-backed and runs inside X11.
  It is not a KMS framebuffer. No pixels reach the display via DRM directly.
- **Single-plane dma-buf only.** Multi-plane (NV12, YUV) buffer imports are not
  implemented. The compositor rejects them with `zwp_linux_buffer_params.failed`.
- **No input handling.** There is no wl_keyboard, wl_pointer, or wl_touch
  implementation. Clients that require input before drawing may stall.
- **wl_output is synthetic.** The advertised output geometry (256×256, 60 Hz) is
  a placeholder and does not reflect the real display.
- **APIs and structure may change.** This is active prototype work. Module names,
  entry points, and internal interfaces are not stable.

---

## Near-Term Technical Priorities

1. Real-client validation: run `weston-terminal`, `mpv --gpu-context=wayland`,
   and `gtk4-demo` against the compositor to find unimplemented protocol paths.
2. Direct scanout: connect the existing `PRIMARY_SCANOUT_ELIGIBLE` classification
   to an actual `drmModeSetCrtc` / `drmModePageFlip` call on a free VT.
3. Multi-plane dma-buf: extend the `zwp_linux_buffer_params_v1` handler to
   accept NV12 and similar formats.
4. Input skeleton: add minimal `wl_keyboard` / `wl_pointer` stubs so clients
   that call `wl_seat.get_keyboard()` do not receive unhandled protocol errors.

---

## Development

```bash
# Archive a source snapshot
bash dev-mktar.sh

# Include untracked files
bash dev-mktar.sh --include-untracked

# Compile-check all warp modules
.venv/bin/python3 -m py_compile warp/protocol/compositor.py warp/gpu/egl_import.py \
  warp/gpu/gles_renderer.py warp/output/kms.py
```

---

## Hardware Tested

| Component | Value |
|-----------|-------|
| Machine | MicroForge |
| GPU | Intel UHD 630 |
| Driver | Mesa / i915 |
| EGL | 1.5 (Mesa) |
| OS | Bodhi Linux 7 (Ubuntu base), Bodhi Trixie (Debian 13 base) |
| Python | 3.13 |

## License
This project is licensed under the GNU General Public License v3.0.