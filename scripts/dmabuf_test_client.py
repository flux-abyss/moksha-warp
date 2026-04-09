#!/usr/bin/env python3
"""
Minimal dma-buf Wayland client for testing moksha-warp.

Allocates GPU-backed buffers via DRM dumb-buffer + prime export, attaches
them to a wl_surface with xdg_shell, and loops continuously so the server
can exercise the full present → release lifecycle.

Usage:
    WAYLAND_DISPLAY=wayland-warp python3 scripts/dmabuf_test_client.py

Requirements:
    pip install pywayland
    /dev/dri/card* readable (user must be in 'video' group)
"""

import ctypes
import ctypes.util
import fcntl
import os
import struct
import sys
import time

# ---------------------------------------------------------------------------
# pywayland imports
# ---------------------------------------------------------------------------
from pywayland.client import Display as WlDisplay
from pywayland.protocol.wayland import (
    WlCompositor,
    WlShm,
    WlSeat,
    WlOutput,
)
from pywayland.protocol.xdg_shell import XdgWmBase
from pywayland.protocol.linux_dmabuf_v1 import ZwpLinuxDmabufV1

# ---------------------------------------------------------------------------
# DRM ioctl constants (Linux/x86-64)
# ---------------------------------------------------------------------------
_DRM_IOCTL_MODE_CREATE_DUMB  = 0xC02064B2
_DRM_IOCTL_MODE_MAP_DUMB     = 0xC01064B3
_DRM_IOCTL_MODE_DESTROY_DUMB = 0xC00464B4
_DRM_IOCTL_PRIME_HANDLE_TO_FD = 0xC00C642D

DRM_FORMAT_XRGB8888 = 0x34325258
DRM_FORMAT_ARGB8888 = 0x34325241

NUM_BUFFERS = 3   # triple-buffer pool so client never stalls
FRAME_DELAY = 1 / 60  # target ~60 fps


def log(*args):
    print(*args, flush=True)


# ---------------------------------------------------------------------------
# DRM dumb-buffer helpers
# ---------------------------------------------------------------------------

class DumbBuffer:
    """One DRM dumb buffer allocated on /dev/dri/card* and exported as prime fd."""

    def __init__(self, drm_fd, width, height, bpp=32):
        self.drm_fd = drm_fd
        self.width  = width
        self.height = height
        self.bpp    = bpp
        self.handle = 0
        self.stride = 0
        self.size   = 0
        self.prime_fd = -1
        self._mmap    = None

        self._create()

    def _create(self):
        # struct drm_mode_create_dumb { height, width, bpp, flags, handle, pitch, size }
        buf = struct.pack("=IIIIQQI",
                          self.height, self.width, self.bpp, 0,
                          0, 0, 0)
        buf = bytearray(buf)
        fcntl.ioctl(self.drm_fd, _DRM_IOCTL_MODE_CREATE_DUMB, buf)
        result = struct.unpack("=IIIIQQI", bytes(buf))
        # result: (height, width, bpp, flags, handle, pitch, size)
        self.handle = result[4]
        self.stride = result[5]
        self.size   = result[6]
        log(f"[dumb] created handle={self.handle} stride={self.stride} size={self.size}")

        # Export prime fd
        # struct drm_prime_handle { handle, flags, fd }
        prime_buf = struct.pack("=IiI", self.handle, 2, -1)  # flags=2 = DRM_CLOEXEC
        prime_buf = bytearray(prime_buf)
        fcntl.ioctl(self.drm_fd, _DRM_IOCTL_PRIME_HANDLE_TO_FD, prime_buf)
        result2 = struct.unpack("=IiI", bytes(prime_buf))
        self.prime_fd = result2[2]
        log(f"[dumb] prime_fd={self.prime_fd}")

    def map(self):
        """Return a mutable mmap of the dumb buffer."""
        if self._mmap is not None:
            return self._mmap
        import mmap
        # struct drm_mode_map_dumb { handle, pad, offset }
        map_buf = struct.pack("=IIQ", self.handle, 0, 0)
        map_buf = bytearray(map_buf)
        fcntl.ioctl(self.drm_fd, _DRM_IOCTL_MODE_MAP_DUMB, map_buf)
        result = struct.unpack("=IIQ", bytes(map_buf))
        offset = result[2]
        self._mmap = mmap.mmap(
            self.drm_fd, self.size,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=offset,
        )
        return self._mmap

    def fill_solid(self, r, g, b):
        """Fill with a solid XRGB8888 colour."""
        pixel = (0xFF << 24) | (r << 16) | (g << 8) | b
        word  = struct.pack("=I", pixel)
        total_pixels = self.stride // 4 * self.height
        mm = self.map()
        mm.seek(0)
        mm.write(word * total_pixels)
        mm.flush()

    def destroy(self):
        if self.prime_fd >= 0:
            try:
                os.close(self.prime_fd)
            except OSError:
                pass
            self.prime_fd = -1
        if self._mmap is not None:
            try:
                self._mmap.close()
            except Exception:
                pass
            self._mmap = None
        if self.handle:
            destroy_buf = struct.pack("=I", self.handle)
            destroy_buf = bytearray(destroy_buf.ljust(4, b"\x00"))
            try:
                fcntl.ioctl(self.drm_fd, _DRM_IOCTL_MODE_DESTROY_DUMB, destroy_buf)
            except OSError as e:
                log(f"[dumb] destroy failed: {e}")
            self.handle = 0


# ---------------------------------------------------------------------------
# Wayland client state
# ---------------------------------------------------------------------------

class ClientState:
    def __init__(self):
        self.display      = None
        self.compositor   = None
        self.xdg_wm_base  = None
        self.dmabuf       = None
        self.surface      = None
        self.xdg_surface  = None
        self.xdg_toplevel = None
        self.configured   = False
        self.width        = 256
        self.height       = 256
        self.running      = True
        self.frame_count  = 0
        # Buffer pool: (DumbBuffer, wl_buffer_proxy, busy:bool)
        self.buffers: list = []
        self.drm_fd = -1


def _open_drm_card():
    import glob
    import stat
    for path in sorted(glob.glob("/dev/dri/card*")):
        try:
            st = os.stat(path)
            if not stat.S_ISCHR(st.st_mode):
                continue
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            log(f"[drm] opened {path} fd={fd}")
            return fd
        except OSError as e:
            log(f"[drm] cannot open {path}: {e}")
    raise RuntimeError("No accessible /dev/dri/card* node found")


def run_client(socket_name="wayland-warp"):
    state = ClientState()

    # Open DRM card for dumb-buffer allocation
    state.drm_fd = _open_drm_card()

    display = WlDisplay()
    display.connect(socket_name)
    log(f"[client] connected to {socket_name}")
    state.display = display

    registry = display.get_registry()

    @registry.dispatcher["global"]
    def on_global(registry, name, interface, version):
        log(f"[client] global {interface} v{version} name={name}")
        if interface == "wl_compositor":
            state.compositor = registry.bind(name, WlCompositor, min(version, 4))
        elif interface == "xdg_wm_base":
            state.xdg_wm_base = registry.bind(name, XdgWmBase, min(version, 1))
            @state.xdg_wm_base.dispatcher["ping"]
            def _ping(xwm, serial):
                xwm.pong(serial)
        elif interface == "zwp_linux_dmabuf_v1":
            state.dmabuf = registry.bind(name, ZwpLinuxDmabufV1, min(version, 3))

    display.roundtrip()
    display.roundtrip()

    if state.compositor is None:
        raise RuntimeError("wl_compositor not found")
    if state.xdg_wm_base is None:
        raise RuntimeError("xdg_wm_base not found")
    if state.dmabuf is None:
        raise RuntimeError("zwp_linux_dmabuf_v1 not found")

    # Create surface + xdg_surface + xdg_toplevel
    state.surface      = state.compositor.create_surface()
    state.xdg_surface  = state.xdg_wm_base.get_xdg_surface(state.surface)
    state.xdg_toplevel = state.xdg_surface.get_toplevel()

    state.xdg_toplevel.set_title("moksha-warp dma-buf test")
    state.xdg_toplevel.set_app_id("moksha.warp.test")

    @state.xdg_surface.dispatcher["configure"]
    def _xdg_configure(xsurf, serial):
        log(f"[client] xdg_surface.configure serial={serial}")
        xsurf.ack_configure(serial)
        state.configured = True

    @state.xdg_toplevel.dispatcher["close"]
    def _toplevel_close(toplevel):
        log("[client] xdg_toplevel.close → shutting down")
        state.running = False

    # Commit with null buffer so the server sends the configure event
    state.surface.commit()
    display.roundtrip()
    display.roundtrip()

    if not state.configured:
        log("[client] warning: xdg_surface.configure not received; proceeding anyway")

    # Allocate dumb-buffer pool → one wl_buffer per slot
    W, H = state.width, state.height
    for i in range(NUM_BUFFERS):
        dumb = DumbBuffer(state.drm_fd, W, H)
        dumb.fill_solid(0x22, 0x22, 0x44)  # initial dark blue

        params = state.dmabuf.create_params()
        params.add(
            dumb.prime_fd,   # fd
            0,               # plane_index
            0,               # offset
            dumb.stride,     # stride
            0,               # modifier_hi
            0,               # modifier_lo
        )

        slot = {"dumb": dumb, "wl_buffer": None, "busy": False, "index": i}

        @params.dispatcher["created"]
        def _created(params_obj, wl_buf, _slot=slot):
            log(f"[client] buffer {_slot['index']} wl_buffer created {wl_buf}")
            _slot["wl_buffer"] = wl_buf

            @wl_buf.dispatcher["release"]
            def _release(buf, _s=_slot):
                log(f"[client] buffer {_s['index']} released")
                _s["busy"] = False

        @params.dispatcher["failed"]
        def _failed(params_obj, _slot=slot):
            log(f"[client] FATAL: buffer {_slot['index']} create_params.failed")
            state.running = False

        params.create(W, H, DRM_FORMAT_XRGB8888, 0)
        state.buffers.append(slot)

    display.roundtrip()
    display.roundtrip()

    # Verify all buffers were created
    for slot in state.buffers:
        if slot["wl_buffer"] is None:
            log(f"[client] FATAL: slot {slot['index']} has no wl_buffer after roundtrip")
            state.running = False

    if not state.running:
        log("[client] aborting: buffer creation failed")
        _cleanup(state)
        return

    log("[client] all buffers created; starting render loop")

    COLOURS = [
        (0xFF, 0x20, 0x20),   # red
        (0x20, 0xFF, 0x20),   # green
        (0x20, 0x20, 0xFF),   # blue
        (0xFF, 0xFF, 0x20),   # yellow
        (0xFF, 0x20, 0xFF),   # magenta
        (0x20, 0xFF, 0xFF),   # cyan
    ]

    frame_pending = False

    def _next_free_slot():
        for s in state.buffers:
            if not s["busy"]:
                return s
        return None

    def _on_frame_done(cb_obj, time_ms):
        nonlocal frame_pending
        frame_pending = False

    while state.running:
        display.dispatch(0)
        display.flush()

        if frame_pending:
            time.sleep(0.001)
            continue

        slot = _next_free_slot()
        if slot is None:
            log("[client] all buffers busy — waiting for release")
            time.sleep(0.005)
            continue

        # Paint a new colour
        r, g, b = COLOURS[state.frame_count % len(COLOURS)]
        slot["dumb"].fill_solid(r, g, b)
        slot["busy"] = True

        state.surface.attach(slot["wl_buffer"], 0, 0)
        state.surface.damage(0, 0, W, H)

        cb = state.surface.frame()
        cb.dispatcher["done"] = _on_frame_done
        frame_pending = True

        state.surface.commit()
        display.flush()

        state.frame_count += 1
        if state.frame_count % 60 == 0:
            log(f"[client] {state.frame_count} frames submitted")

    _cleanup(state)


def _cleanup(state):
    log("[client] cleaning up")
    for slot in state.buffers:
        if slot["wl_buffer"] is not None:
            try:
                slot["wl_buffer"].destroy()
            except Exception:
                pass
        slot["dumb"].destroy()
    if state.drm_fd >= 0:
        try:
            os.close(state.drm_fd)
        except OSError:
            pass
    if state.display is not None:
        try:
            state.display.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    socket = os.environ.get("WAYLAND_DISPLAY", "wayland-warp")
    log(f"[client] connecting to {socket}")
    try:
        run_client(socket)
    except KeyboardInterrupt:
        log("[client] interrupted")
    except Exception as e:
        log(f"[client] fatal: {e!r}")
        raise
