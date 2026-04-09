#!/usr/bin/env python3
import json
import mmap
import os
import signal
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pygame
from warp.gpu.gles_renderer import GlesDmabufRenderer
from pywayland import ffi, lib
from pywayland.server import Display
from pywayland.protocol.wayland import (
    WlBuffer,
    WlCallback,
    WlCompositor,
    WlOutput,
    WlSeat,
    WlShm,
    WlShmPool,
    WlSurface,
)
from pywayland.protocol.xdg_shell import (
    XdgSurface,
    XdgToplevel,
    XdgWmBase,
)
from pywayland.protocol.linux_dmabuf_v1 import (
    ZwpLinuxDmabufV1,
    ZwpLinuxBufferParamsV1,
)
from warp.gpu.egl_import import EglDmabufImporter, EglDmabufError
from warp.output.kms import (
    DirectScanoutError,
    GlesPreviewBackend,
    KmsDirectBackend,
)

LOG_PATH = os.path.expanduser("~/repos/moksha-warp/logs/wayland_globals_probe.json")

DRM_FORMAT_XRGB8888 = 0x34325258
DRM_FORMAT_ARGB8888 = 0x34325241
DRM_FORMAT_MOD_LINEAR_HI = 0
DRM_FORMAT_MOD_LINEAR_LO = 0

DMABUF_PARAMS = {}
DMABUF_GL_RENDERER = None
EGL_DMABUF_IMPORTER = None

# GL function type for glEGLImageTargetTexture2DOES — needed for buffer teardown
import ctypes as _ctypes


def log(*args):
    print(*args, flush=True)


def _patch_pywayland_server():
    """Fix pywayland 0.4.18 for server-side (compositor) use.

    TWO independent bugs, both fatal:

    Bug 1 -- dispatcher_func gets NULL (primary crash):
    libwayland 1.23 (connection.c wl_closure_dispatch) calls the dispatcher as:
        dispatcher(target->implementation, target, opcode, ...)
    where 'target' is the wl_resource's embedded wl_object*.

    Resource.__init__ calls wl_resource_set_dispatcher with:
        implementation = ffi.NULL       <- becomes arg1 of dispatcher_func
        data           = self._handle   <- stored as resource->data, NOT passed

    So dispatcher_func receives data=ffi.NULL → ffi.from_handle(NULL) → crash.

    Fix: swap the arguments — pass self._handle as 'implementation' so it
    arrives as the first arg to dispatcher_func, and put ffi.NULL in 'data'.

    resource_destroy_func reads the handle via wl_resource_get_user_data, which
    returns resource->data (NOT resource->object.implementation). So we also
    need to store the handle in BOTH slots, or patch resource_destroy_func to
    read from the right place.  Simplest: pass self._handle to BOTH slots.

    Bug 2 -- NewId arguments corrupt wl_resources (secondary):
    Message.c_to_arguments NewId branch constructs a client-side Proxy from
    arg_ptr.o (which on the server side is a wl_resource*). Proxy.__init__
    attaches ffi.gc(ptr, wl_proxy_destroy), destroying the resource when the
    Proxy is GC'd. Fix: read arg_ptr.n (the uint32 new-object ID) directly.
    """
    from pywayland.protocol_core.resource import Resource
    from pywayland.protocol_core.message import Message
    from pywayland.scanner.argument import ArgumentType as AT
    from pywayland import ffi, lib
    import traceback as _tb

    # Module-level set that keeps all active ffi.new_handle() values alive.
    # The handle (and the Python object it wraps) must not be GC'd while
    # libwayland holds a pointer to the handle's address.
    # The set is populated on Resource.__init__ and cleared after
    # resource_destroy_func has finished calling our destructor.
    import builtins as _builtins
    if not hasattr(_builtins, "_WARP_LIVE_HANDLES"):
        _builtins._WARP_LIVE_HANDLES = set()
    _LIVE_HANDLES = _builtins._WARP_LIVE_HANDLES

    # ---- Bug 1 fix: patch Resource.__init__ --------------------------------
    _orig_resource_init = Resource.__init__

    def _patched_resource_init(self, client, version=None, id=0):
        # Replicate the original logic but swap implementation/data.
        if version is None:
            version = self.interface.version

        self.version = version
        from pywayland.dispatcher import Dispatcher
        self.dispatcher = Dispatcher(self.interface.requests, destructor=True)

        from pywayland.server.client import Client
        if isinstance(client, Client):
            client_ptr = client._ptr
        else:
            client_ptr = client
        assert client_ptr is not None

        self._ptr = lib.wl_resource_create(
            client_ptr, self.interface._ptr, version, id
        )
        self.id = lib.wl_resource_get_id(self._ptr)

        if self.dispatcher is not None:
            self._handle = ffi.new_handle(self)
            # Keep the handle alive in the module-level set so the Python
            # object cannot be GC'd while libwayland holds its address.
            _LIVE_HANDLES.add(self._handle)
            # KEY FIX: pass self._handle as 'implementation' (3rd arg), not
            # 'data' (4th arg).  libwayland dispatcher_func receives
            # target->implementation as its first argument, so this makes
            # ffi.from_handle(data) in dispatcher_func work correctly.
            # Also pass self._handle as 'data' so resource_destroy_func (which
            # calls wl_resource_get_user_data) can also find it.
            lib.wl_resource_set_dispatcher(
                self._ptr,
                lib.dispatcher_func,
                self._handle,
                self._handle,
                lib.resource_destroy_func,
            )

    Resource.__init__ = _patched_resource_init


    # ---- Bug 2 fix: patch Message.c_to_arguments --------------------------

    def _patched_c_to_args(self, args_ptr):
        args = []
        for i, argument in enumerate(self.arguments):
            arg_ptr = args_ptr[i]
            if argument.argument_type == AT.NewId:
                # Server-side: arg_ptr.n is the new uint32 object ID.
                # DO NOT construct a Proxy — that calls wl_proxy_destroy on
                # what is actually a wl_resource*, destroying it prematurely.
                args.append(arg_ptr.n)
            elif argument.argument_type == AT.Int:
                args.append(arg_ptr.i)
            elif argument.argument_type == AT.Uint:
                args.append(arg_ptr.u)
            elif argument.argument_type == AT.Fixed:
                args.append(lib.wl_fixed_to_double(arg_ptr.f))
            elif argument.argument_type == AT.FileDescriptor:
                args.append(arg_ptr.h)
            elif argument.argument_type == AT.String:
                if arg_ptr.s == ffi.NULL:
                    if not argument.nullable:
                        raise RuntimeError(
                            f"NULL string for non-nullable arg in '{self.name}'"
                        )
                    args.append(None)
                else:
                    args.append(ffi.string(arg_ptr.s).decode())
            elif argument.argument_type == AT.Object:
                if arg_ptr.o == ffi.NULL:
                    if not argument.nullable:
                        raise RuntimeError(
                            f"Got null object parsing arguments for '{self.name}' "
                            "message, may already be destroyed"
                        )
                    args.append(None)
                else:
                    iface = argument.interface
                    proxy_ptr = ffi.cast("struct wl_proxy *", arg_ptr.o)
                    obj = iface.registry.get(proxy_ptr)
                    if obj is None:
                        raise RuntimeError(
                            f"Unable to get object for {proxy_ptr} in "
                            f"'{self.name}', was it garbage collected?"
                        )
                    args.append(obj)
            elif argument.argument_type == AT.Array:
                array_ptr = arg_ptr.a
                args.append(ffi.buffer(array_ptr.data, array_ptr.size)[:])
            else:
                raise RuntimeError(f"Unknown argument type: {argument.argument_type}")
        return args

    Message.c_to_arguments = _patched_c_to_args

    log("[pywayland-patch] Resource.__init__ patched: implementation=handle (Bug 1 fix)")
    log("[pywayland-patch] Message.c_to_arguments patched: NewId→int (Bug 2 fix)")


_patch_pywayland_server()



@dataclass
class ShmPoolState:
    fd: int
    size: int
    mm: mmap.mmap
    refcount: int = 0
    destroyed: bool = False
    closed: bool = False

    def maybe_cleanup(self):
        if self.closed:
            return
        if not self.destroyed:
            return
        if self.refcount != 0:
            return

        try:
            self.mm.close()
        except Exception:
            pass

        try:
            os.close(self.fd)
        except Exception:
            pass

        self.closed = True


@dataclass
class BufferState:
    pool: ShmPoolState
    offset: int
    width: int
    height: int
    stride: int
    format: int
    released: bool = False   # True once wl_buffer.release has been sent
    presented: bool = False  # True once this buffer has been on-screen


@dataclass
class DmabufBufferState:
    width: int
    height: int
    format: int
    modifier: int
    planes: list
    egl_image: Optional[object] = None
    gl_texture: Optional[int] = None  # lazy-created per-buffer GL texture
    released: bool = False            # True once wl_buffer.release has been sent
    presented: bool = False           # True once this buffer has been on screen


@dataclass
class SurfaceState:
    pending_buffer: Optional[object] = None
    current_buffer: Optional[object] = None
    previous_buffer: Optional[object] = None          # buffer displayed last frame
    pending_buffer_resource: Optional[WlBuffer.resource_class] = None
    current_buffer_resource: Optional[WlBuffer.resource_class] = None
    previous_buffer_resource: Optional[WlBuffer.resource_class] = None  # for post-present release
    frame_callbacks: List[WlCallback.resource_class] = field(default_factory=list)
    # Surface-level state tracked for direct-scanout eligibility
    pending_buffer_transform: int = 0   # WL_OUTPUT_TRANSFORM_NORMAL = 0
    current_buffer_transform: int = 0
    pending_buffer_scale: int = 1
    current_buffer_scale: int = 1
    # Damage rect union for the pending frame: (x, y, x2, y2) or None = unknown
    pending_damage_rects: Optional[List] = field(default_factory=list)
    current_damage_rects: Optional[List] = field(default_factory=list)
    # Surface metadata
    width: int = 0
    height: int = 0
    title: str = ""


class ProbeState:
    def __init__(self):
        self.globals: List[str] = []
        self.buffers: Dict[int, WlBuffer.resource_class] = {}
        self.surfaces: Dict[int, WlSurface.resource_class] = {}
        self.pools: Dict[int, WlShmPool.resource_class] = {}
        self.bound_resources: Dict[tuple, object] = {}
        self.callbacks: Dict[int, WlCallback.resource_class] = {}
        self.xdg_surfaces: Dict[int, XdgSurface.resource_class] = {}
        self.xdg_toplevels: Dict[int, XdgToplevel.resource_class] = {}
        self.xdg_wm_bases: Dict[int, object] = {}  # tracked for compositor-side ping
        self.server_globals: List[object] = []
        self.serial = 1
        self.socket_name: Optional[str] = None
        self.last_ping_time: float = 0.0

    def next_serial(self) -> int:
        self.serial += 1
        return self.serial


STATE = ProbeState()


class PygameRenderer:
    def __init__(self):
        self.screen = None
        self.size = (640, 480)
        self.started = False

    def start(self):
        if not self.started:
            pygame.init()
            self.started = True

    def ensure_window(self, width: int, height: int):
        self.start()
        if self.screen is None or self.size != (width, height):
            self.size = (width, height)
            self.screen = pygame.display.set_mode(self.size)
            pygame.display.set_caption("moksha-warp shm preview")
            log(f"[renderer] window ready {width}x{height}")

    def pump(self):
        if not self.started:
            return
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise SystemExit(0)

    def present_buffer(self, buf_state: BufferState):
        # Accept both ARGB8888 (0) and XRGB8888 (1) — same 4-byte BGRA layout;
        # alpha channel is simply ignored for the preview window.
        if buf_state.format not in (0, 1):
            log(f"[renderer] unsupported shm format: {buf_state.format}")
            return

        width = buf_state.width
        height = buf_state.height
        stride = buf_state.stride
        offset = buf_state.offset
        mm = buf_state.pool.mm

        expected_row_bytes = width * 4
        total_bytes = stride * height

        if offset + total_bytes > buf_state.pool.size:
            log(
                f"[renderer] buffer outside pool bounds: "
                f"offset={offset} total={total_bytes} pool_size={buf_state.pool.size}"
            )
            return

        raw = memoryview(mm)[offset : offset + total_bytes]
        self.ensure_window(width, height)

        if stride == expected_row_bytes:
            surf = pygame.image.frombuffer(raw, (width, height), "BGRA")
            self.screen.blit(surf, (0, 0))
        else:
            packed = bytearray(expected_row_bytes * height)
            for y in range(height):
                src_start = y * stride
                src_end = src_start + expected_row_bytes
                dst_start = y * expected_row_bytes
                packed[dst_start : dst_start + expected_row_bytes] = raw[src_start:src_end]
            surf = pygame.image.frombuffer(packed, (width, height), "BGRA")
            self.screen.blit(surf, (0, 0))

        pygame.display.flip()
        log(
            f"[renderer] presented buffer "
            f"{width}x{height} stride={stride} offset={offset} fmt={buf_state.format}"
        )


RENDERER = PygameRenderer()

# Output backends — instantiated once at module level.
# KmsDirectBackend runs its DRM probe immediately on construction.
GLES_BACKEND: GlesPreviewBackend = GlesPreviewBackend()
GLES_BACKEND.set_shm_renderer(RENDERER)
# KMS_BACKEND is constructed lazily in ShmPreviewBridge.setup() after we have
# the log function ready. Declared here so commit() can reference it.
KMS_BACKEND: Optional[KmsDirectBackend] = None

# ---------------------------------------------------------------------------
# Direct-scanout eligibility detector
# ---------------------------------------------------------------------------

# Formats that KMS can directly scan out (same set we advertise via linux_dmabuf)
SCANOUT_FORMATS = {DRM_FORMAT_XRGB8888, DRM_FORMAT_ARGB8888}

# Only DRM_FORMAT_MOD_LINEAR (== 0) is eligible for direct scanout here
SCANOUT_MODIFIERS = {0}

# Eligibility result tokens
PRIMARY_SCANOUT_ELIGIBLE = "PRIMARY_SCANOUT_ELIGIBLE"
PLANE_CANDIDATE          = "PLANE_CANDIDATE"
BLOCKED                  = "BLOCKED"


def _fourcc_str(fmt: int) -> str:
    """Return the four-character code string for a DRM format integer."""
    return "".join(chr((fmt >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def _damage_covers_buffer(rects: list, bw: int, bh: int) -> bool:
    """Return True if the union of *rects* covers the entire buffer area.

    Each rect is (x1, y1, x2, y2) in buffer-space pixels.
    A single full-extent rect is the common fast path.
    """
    if not rects:
        return False  # no damage sent → cannot confirm full coverage
    # Fast path: any single rect that covers the whole buffer
    for x1, y1, x2, y2 in rects:
        if x1 <= 0 and y1 <= 0 and x2 >= bw and y2 >= bh:
            return True
    # General path: build the union bounding box and check
    ux1 = min(r[0] for r in rects)
    uy1 = min(r[1] for r in rects)
    ux2 = max(r[2] for r in rects)
    uy2 = max(r[3] for r in rects)
    return ux1 <= 0 and uy1 <= 0 and ux2 >= bw and uy2 >= bh


def check_direct_scanout_eligibility(
    surface_id: int, surf_state: "SurfaceState", buf
) -> str:
    """Return PRIMARY_SCANOUT_ELIGIBLE, PLANE_CANDIDATE, or BLOCKED.

    PRIMARY_SCANOUT_ELIGIBLE: buffer can be handed directly to drmModeSetCrtc.
    PLANE_CANDIDATE:          format/modifier/transform OK but size doesn't match
                              the primary mode — could be used on an overlay plane.
    BLOCKED:                  fundamentally incompatible (SHM, bad format, etc.).
    """
    try:
        # Rule 1: exactly one visible surface
        visible = [
            s for s in STATE.surfaces.values()
            if s.state.current_buffer is not None
        ]
        if len(visible) != 1:
            log(f"[direct-scanout] blocked: multiple surfaces (count={len(visible)})")
            return BLOCKED

        # SHM buffers can never be scanned out directly
        if not isinstance(buf, DmabufBufferState):
            log("[direct-scanout] blocked: shm buffer (not dmabuf)")
            return BLOCKED

        # Rule 5: supported pixel format
        if buf.format not in SCANOUT_FORMATS:
            log(f"[direct-scanout] blocked: unsupported format (fourcc=0x{buf.format:08X})")
            return BLOCKED

        # Rule 6: linear modifier only
        if buf.modifier not in SCANOUT_MODIFIERS:
            log(f"[direct-scanout] blocked: modifier unsupported (modifier={buf.modifier})")
            return BLOCKED

        # Rule 4: no rotation / transform
        if surf_state.current_buffer_transform != 0:
            log(
                f"[direct-scanout] blocked: transform present"
                f" (transform={surf_state.current_buffer_transform})"
            )
            return BLOCKED

        # Rule 3: no integer up/down-scaling
        if surf_state.current_buffer_scale != 1:
            log(
                f"[direct-scanout] blocked: scaling requested"
                f" (scale={surf_state.current_buffer_scale})"
            )
            return BLOCKED

        # Rule 7: damage must fully cover the buffer (not partial)
        rects = surf_state.current_damage_rects or []
        if rects:
            if not _damage_covers_buffer(rects, buf.width, buf.height):
                log("[direct-scanout] blocked: damage region partial")
                return BLOCKED
        else:
            # No damage rects recorded at all — coverage unknown
            log("[direct-scanout] blocked: damage region unknown (no rects received)")
            return BLOCKED

        # Rule 2: buffer size must match the real KMS mode for primary scanout.
        # Derive mode size from KMS_BACKEND; fall back to PLANE_CANDIDATE if unknown.
        fourcc = _fourcc_str(buf.format)
        mode_size = KMS_BACKEND.kms_mode_size if KMS_BACKEND is not None else None
        if mode_size is not None:
            mode_w, mode_h = mode_size
        else:
            # No KMS backend / no mode detected — cannot confirm primary eligibility
            log(
                f"[direct-scanout] plane-candidate: no KMS mode known"
                f" buffer={buf.width}x{buf.height} format={fourcc} modifier={buf.modifier}"
            )
            return PLANE_CANDIDATE

        if buf.width == mode_w and buf.height == mode_h:
            log(
                f"[direct-scanout] PRIMARY_SCANOUT_ELIGIBLE"
                f" surface={surface_id}"
                f" size={buf.width}x{buf.height}"
                f" mode={mode_w}x{mode_h}"
                f" format={fourcc}"
                f" modifier={buf.modifier}"
            )
            return PRIMARY_SCANOUT_ELIGIBLE
        else:
            log(
                f"[direct-scanout] plane-candidate:"
                f" buffer={buf.width}x{buf.height}"
                f" mode={mode_w}x{mode_h}"
                f" format={fourcc}"
                f" modifier={buf.modifier}"
            )
            return PLANE_CANDIDATE

    except Exception as e:
        log("[direct-scanout] eligibility check error:", repr(e))
        return BLOCKED



def save_report():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    data = {
        "socket_name": STATE.socket_name,
        "globals": STATE.globals,
        "buffer_count": len(STATE.buffers),
        "surface_count": len(STATE.surfaces),
        "pool_count": len(STATE.pools),
    }
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log(f"Report saved to {LOG_PATH}")


class MyCallbackResource(WlCallback.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        if self._ptr:
            self.interface.registry[self._ptr] = self
        # Null _ptr on destroy so fire-and-forget done() calls after client
        # disconnect raise @ensure_valid instead of segfaulting.
        self.dispatcher.destructor = lambda res: setattr(res, '_ptr', None)
        log("MyCallbackResource.__init__ id=", id_)


def _teardown_dmabuf_buffer_state(state: "DmabufBufferState", buf_id) -> None:
    """Release all GPU/OS resources held by a DmabufBufferState.

    Called from both the libwayland destroy callback and the explicit
    destroy() path.  Safe to call multiple times (guards on None checks).
    """
    # Destroy the GL texture
    tex = state.gl_texture
    if tex is not None:
        state.gl_texture = None
        renderer = DMABUF_GL_RENDERER
        if renderer is not None and renderer.ready:
            try:
                tid = _ctypes.c_uint(tex)
                renderer.libgles.glDeleteTextures(1, _ctypes.byref(tid))
                log(f"[teardown] GL texture deleted tex={tex} buf={buf_id}")
            except Exception as exc:
                log(f"[teardown] glDeleteTextures failed buf={buf_id}: {exc!r}")

    # Destroy the EGLImage
    img = state.egl_image
    if img is not None:
        state.egl_image = None
        importer = EGL_DMABUF_IMPORTER
        if importer is not None:
            try:
                importer.destroy_image(img)
                log(f"[teardown] EGLImage destroyed image={img} buf={buf_id}")
            except Exception as exc:
                log(f"[teardown] EGLImage destroy failed buf={buf_id}: {exc!r}")

    # Close duplicated plane fds
    for p in state.planes:
        fd = p.get("fd")
        if fd is not None and fd >= 0:
            try:
                os.close(fd)
                p["fd"] = -1
                log(f"[teardown] plane fd closed fd={fd} buf={buf_id}")
            except OSError as exc:
                log(f"[teardown] close fd={fd} failed buf={buf_id}: {exc!r}")


class MyBufferResource(WlBuffer.resource_class):
    def __init__(self, client, version, id_, state):
        super().__init__(client, version, id_)
        self.state = state
        if self._ptr:
            self.interface.registry[self._ptr] = self
        def _buffer_destroyed(res):
            log("MyBufferResource libwayland-destroyed id=", res.id)
            res._ptr = None
            try:
                if isinstance(res.state, BufferState):
                    res.state.pool.refcount -= 1
                    res.state.pool.maybe_cleanup()
                elif isinstance(res.state, DmabufBufferState):
                    _teardown_dmabuf_buffer_state(res.state, res.id)
            except Exception as exc:
                log("MyBufferResource libwayland-destroyed teardown error:", repr(exc))
            STATE.buffers.pop(res.id, None)
        self.dispatcher.destructor = _buffer_destroyed
        STATE.buffers[id_] = self
        log("MyBufferResource.__init__ id=", id_)

    def destroy(self):
        log("MyBufferResource.destroy id=", self.id)
        try:
            if isinstance(self.state, BufferState):
                self.state.pool.refcount -= 1
                log("ShmPoolState.refcount-- buffer_id=", self.id, "refcount=", self.state.pool.refcount)
                self.state.pool.maybe_cleanup()
            elif isinstance(self.state, DmabufBufferState):
                _teardown_dmabuf_buffer_state(self.state, self.id)
        except Exception as e:
            log("MyBufferResource.destroy teardown failed:", repr(e))
        STATE.buffers.pop(self.id, None)
        super().destroy()


class MyShmPoolResource(WlShmPool.resource_class):
    def __init__(self, client, version, id_, fd, size):
        super().__init__(client, version, id_)
        if self._ptr:
            self.interface.registry[self._ptr] = self
        def _pool_destroyed(res):
            log("MyShmPoolResource libwayland-destroyed id=", res.id)
            res._ptr = None
            STATE.pools.pop(res.id, None)
        self.dispatcher.destructor = _pool_destroyed
        dup_fd = os.dup(fd)
        mm = mmap.mmap(dup_fd, size, access=mmap.ACCESS_READ)
        self.state = ShmPoolState(dup_fd, size, mm)
        STATE.pools[id_] = self
        log(
            "MyShmPoolResource.__init__ client=",
            client,
            "version=",
            version,
            "id=",
            id_,
            "fd=",
            dup_fd,
            "size=",
            size,
        )

    def destroy(self):
        log("MyShmPoolResource.destroy id=", self.id, "(resource only)")
        STATE.pools.pop(self.id, None)
        super().destroy()


class MyWlSurfaceResource(WlSurface.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        self.state = SurfaceState()
        if self._ptr:
            self.interface.registry[self._ptr] = self
        def _surf_destroyed(res):
            log("MyWlSurfaceResource libwayland-destroyed id=", res.id)
            res._ptr = None
            STATE.surfaces.pop(res.id, None)
        self.dispatcher.destructor = _surf_destroyed
        STATE.surfaces[id_] = self
        log("MyWlSurfaceResource.__init__ id=", id_)


class MyXdgSurfaceResource(XdgSurface.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        self.last_configure = None
        if self._ptr:
            self.interface.registry[self._ptr] = self
        def _xsurf_destroyed(res):
            log("MyXdgSurfaceResource libwayland-destroyed id=", res.id)
            res._ptr = None
            STATE.xdg_surfaces.pop(res.id, None)
        self.dispatcher.destructor = _xsurf_destroyed
        log("MyXdgSurfaceResource.__init__ id=", id_)


class MyXdgToplevelResource(XdgToplevel.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        if self._ptr:
            self.interface.registry[self._ptr] = self
        def _xtop_destroyed(res):
            log("MyXdgToplevelResource libwayland-destroyed id=", res.id)
            res._ptr = None
            STATE.xdg_toplevels.pop(res.id, None)
        self.dispatcher.destructor = _xtop_destroyed
        log("MyXdgToplevelResource.__init__ id=", id_)


def _register_resource(resource):
    """Register a server-side resource in its interface registry.

    pywayland 0.4.18 populates iface.registry only in Proxy.__init__ (client
    side).  Any server-side resource that may be referenced as an Object-type
    argument in a later request MUST be registered here so that
    Message.c_to_arguments can look it up.
    """
    if resource._ptr:
        resource.interface.registry[resource._ptr] = resource


def bind_wl_compositor(resource):
    log("compositor_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("wl_compositor", resource.id)] = resource
    resource.dispatcher.destructor = lambda res: (
        setattr(res, '_ptr', None),
        STATE.bound_resources.pop(("wl_compositor", res.id), None),
    )

    def create_surface(res, id_):
        log("wl_compositor.create_surface id=", id_)
        surf = MyWlSurfaceResource(lib.wl_resource_get_client(res._ptr), res.version, id_)
        STATE.surfaces[id_] = surf

        def destroy_surface(sres):
            log(f"[surface] destroy id={sres.id}")
            # Fire any pending frame callbacks so the client isn't left waiting
            pending_cbs = surf.state.frame_callbacks[:]
            surf.state.frame_callbacks.clear()
            now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
            for cb in pending_cbs:
                cb_id = getattr(cb, 'id', '?')
                try:
                    cb.done(now_ms)
                except Exception:
                    pass
                try:
                    if cb._ptr is not None:
                        lib.wl_resource_destroy(cb._ptr)
                except Exception:
                    pass
            # Release the currently displayed buffer so the client can reuse it
            cur_res = surf.state.current_buffer_resource
            cur_buf = surf.state.current_buffer
            if cur_res is not None and cur_buf is not None and not cur_buf.released:
                try:
                    cur_res.release()
                    cur_buf.released = True
                    log(f"[release] current buffer released on surface destroy id={getattr(cur_res, 'id', '?')}")
                except Exception as exc:
                    log(f"[release] release on surface destroy failed: {exc!r}")
            surf.state.current_buffer = None
            surf.state.current_buffer_resource = None
            surf.state.previous_buffer = None
            surf.state.previous_buffer_resource = None
            STATE.surfaces.pop(sres.id, None)
            # NOTE: do NOT call sres.destroy() here.
            # That would call lib.wl_resource_destroy() prematurely, which fires
            # resource_destroy_func → our destructor.  libwayland will then fire
            # it AGAIN on client cleanup → double-free of _handle → crash.
            # libwayland owns the resource lifetime; we only do Python teardown.


        def attach(sres, buffer, x, y):
            log("wl_surface.attach buffer=", buffer, "x=", x, "y=", y)
            if buffer is None:
                surf.state.pending_buffer = None
                surf.state.pending_buffer_resource = None
                return
            try:
                surf.state.pending_buffer = buffer.state
                surf.state.pending_buffer_resource = buffer
                # Reset released flag so the buffer can be released again
                # after the next present.  A client may attach the same
                # buffer multiple times (single-buffer Mesa EGL scenario).
                buffer.state.released = False
            except AttributeError:
                log("wl_surface.attach: buffer has no .state")
                surf.state.pending_buffer = None
                surf.state.pending_buffer_resource = None

        def damage(sres, x, y, width, height):
            log("wl_surface.damage x=", x, "y=", y, "w=", width, "h=", height)
            if surf.state.pending_damage_rects is not None:
                surf.state.pending_damage_rects.append((x, y, x + width, y + height))

        def frame(sres, callback_id):
            log("wl_surface.frame callback_id=", callback_id)
            cb = MyCallbackResource(
                lib.wl_resource_get_client(sres._ptr),
                sres.version,
                callback_id,
            )
            STATE.callbacks[callback_id] = cb
            surf.state.frame_callbacks.append(cb)
        def commit(sres):
            surf = STATE.surfaces.get(sres.id)
            log(f"[commit] wl_surface.commit id={sres.id}")

            if surf is None:
                return

            # promote pending -> current, save old current as previous
            if surf.state.pending_buffer_resource is not None:
                # Save the buffer currently on-screen so we can release it
                # AFTER the new frame is successfully presented.
                surf.state.previous_buffer          = surf.state.current_buffer
                surf.state.previous_buffer_resource = surf.state.current_buffer_resource

                surf.state.current_buffer          = surf.state.pending_buffer
                surf.state.current_buffer_resource = surf.state.pending_buffer_resource
                surf.state.pending_buffer          = None
                surf.state.pending_buffer_resource = None

                # Update surface dimensions from new buffer
                if surf.state.current_buffer is not None:
                    surf.state.width  = surf.state.current_buffer.width
                    surf.state.height = surf.state.current_buffer.height

            elif surf.state.pending_buffer is None:
                # Explicit null-attach: detach current buffer
                surf.state.previous_buffer          = surf.state.current_buffer
                surf.state.previous_buffer_resource = surf.state.current_buffer_resource
                surf.state.current_buffer           = None
                surf.state.current_buffer_resource  = None

            # Promote surface-level pending state → current
            surf.state.current_buffer_transform = surf.state.pending_buffer_transform
            surf.state.current_buffer_scale     = surf.state.pending_buffer_scale
            surf.state.current_damage_rects     = surf.state.pending_damage_rects
            surf.state.pending_damage_rects     = []  # reset for next frame

            # present current buffer
            buf     = surf.state.current_buffer
            present_ok = False

            if buf is not None:
                try:
                    if isinstance(buf, DmabufBufferState):
                        # Always go through the GLES path for visible preview.
                        # KMS direct-scanout is a separate, future milestone.
                        log(
                            f"[commit] dmabuf buffer committed"
                            f" surface={sres.id} {buf.width}x{buf.height}"
                            f" fourcc=0x{buf.format:08X}"
                        )
                        renderer = DMABUF_GL_RENDERER
                        if renderer is not None and renderer.ready:
                            present_ok = renderer.present_buffer(
                                sres.id, buf,
                                egl_importer=EGL_DMABUF_IMPORTER,
                            )
                            if not present_ok:
                                log(
                                    f"[gles] present_buffer returned False"
                                    f" surface={sres.id}, frame dropped"
                                )
                        else:
                            log("[gles] renderer not ready yet; skipping present")

                    elif isinstance(buf, BufferState):
                        log("[renderer] shm buffer committed")
                        try:
                            GLES_BACKEND.present_shm(buf)
                            present_ok = True
                            # SHM: pixel data is CPU-copied during present_shm().
                            # The compositor no longer holds a reference to the
                            # client's shared memory, so release immediately.
                            # This allows single-buffer clients (Mesa EGL with
                            # one wl_shm buffer) to render the next frame without
                            # waiting for a "previous buffer" release on frame N+1.
                            cur_res = surf.state.current_buffer_resource
                            if cur_res is not None and not buf.released:
                                try:
                                    cur_res.release()
                                    buf.released = True
                                    log("[release] shm buffer released immediately id=",
                                        getattr(cur_res, 'id', '?'))
                                except Exception as re:
                                    log("[release] shm immediate release failed:", repr(re))
                        except Exception as e:
                            log("[renderer] shm present failed:", repr(e))
                    else:
                        log("[renderer] unknown buffer type on commit:", type(buf))

                except Exception as e:
                    log("present error in commit:", repr(e))

            # post-present release: release PREVIOUS buffer, not current
            # only release after a successful present of the new frame;
            # if present failed, hold both so the client cannot reuse them
            if present_ok:
                buf.presented = True
                prev_buf = surf.state.previous_buffer
                prev_res = surf.state.previous_buffer_resource
                if prev_res is not None and prev_buf is not None and not prev_buf.released:
                    try:
                        log(
                            "[release] wl_buffer.release previous id=",
                            getattr(prev_res, "id", None),
                        )
                        prev_res.release()
                        prev_buf.released = True
                    except Exception as e:
                        log("[release] wl_buffer.release failed:", repr(e))
                # Clear previous reference — it has been released
                surf.state.previous_buffer          = None
                surf.state.previous_buffer_resource = None

            # frame callbacks: always fire, even on present failure
            # wl_callback.done is a destructor event: the spec requires the
            # server to call wl_resource_destroy immediately after sending it.
            # Without destroy, Mesa EGL's Wayland platform never unref's the
            # callback and the client stalls waiting for the resource to be freed.
            callbacks = surf.state.frame_callbacks[:]
            surf.state.frame_callbacks.clear()
            now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
            for cb in callbacks:
                cb_id = getattr(cb, 'id', '?')
                try:
                    cb.done(now_ms)
                    log("frame callback done sent id=", cb_id, "ms=", now_ms)
                except Exception as e:
                    log("frame callback done failed id=", cb_id, repr(e))
                # Destroy server-side resource regardless of done() success.
                # This frees the protocol object slot and satisfies Mesa EGL.
                try:
                    if cb._ptr is not None:
                        lib.wl_resource_destroy(cb._ptr)
                        # _ptr will be nulled by resource_destroy_func → our destructor
                except Exception as e:
                    log("frame callback destroy failed id=", cb_id, repr(e))


        def set_opaque_region(sres, region):

            log("wl_surface.set_opaque_region region=", region)

        def set_input_region(sres, region):
            log("wl_surface.set_input_region region=", region)

        def set_buffer_transform(sres, transform):
            surf.state.pending_buffer_transform = transform
            log("wl_surface.set_buffer_transform transform=", transform)

        def set_buffer_scale(sres, scale):
            surf.state.pending_buffer_scale = scale
            log("wl_surface.set_buffer_scale scale=", scale)

        def damage_buffer(sres, x, y, width, height):
            log("wl_surface.damage_buffer x=", x, "y=", y, "w=", width, "h=", height)
            if surf.state.pending_damage_rects is not None:
                surf.state.pending_damage_rects.append((x, y, x + width, y + height))

        surf.dispatcher["destroy"] = destroy_surface
        surf.dispatcher["attach"] = attach
        surf.dispatcher["damage"] = damage
        surf.dispatcher["frame"] = frame
        surf.dispatcher["set_opaque_region"] = set_opaque_region
        surf.dispatcher["set_input_region"] = set_input_region
        surf.dispatcher["commit"] = commit

        message_names = [m.name for m in surf.dispatcher.messages]
        if "set_buffer_transform" in message_names:
            surf.dispatcher["set_buffer_transform"] = set_buffer_transform
        if "set_buffer_scale" in message_names:
            surf.dispatcher["set_buffer_scale"] = set_buffer_scale
        if "damage_buffer" in message_names:
            surf.dispatcher["damage_buffer"] = damage_buffer

    def create_region(res, id_):
        log("wl_compositor.create_region id=", id_, "(stubbed)")

    resource.dispatcher["create_surface"] = create_surface
    resource.dispatcher["create_region"] = create_region


def bind_wl_shm(resource):
    log("shm_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("wl_shm", resource.id)] = resource
    resource.dispatcher.destructor = lambda res: (
        setattr(res, '_ptr', None),
        STATE.bound_resources.pop(("wl_shm", res.id), None),
    )

    try:
        # Advertise both ARGB8888 (0) and XRGB8888 (1) — the two mandatory
        # SHM formats.  Most clients (weston-simple-shm, GTK, etc.) require
        # XRGB8888; omitting it causes immediate "WL_SHM_FORMAT_XRGB32 not
        # available" exit before any surface is created.
        resource.format(0)  # WL_SHM_FORMAT_ARGB8888
        resource.format(1)  # WL_SHM_FORMAT_XRGB8888
    except Exception as e:
        log("shm.format failed:", repr(e))

    def create_pool(res, id_, fd, size):
        log("shm.create_pool id=", id_, "fd=", fd, "size=", size)
        pool = MyShmPoolResource(lib.wl_resource_get_client(res._ptr), res.version, id_, fd, size)
        STATE.pools[id_] = pool

        def create_buffer(pres, id2, offset, width, height, stride, format_):
            log(
                "MyShmPoolResource.create_buffer",
                f"id={id2}",
                f"offset={offset}",
                f"width={width}",
                f"height={height}",
                f"stride={stride}",
                f"format={format_}",
            )
            pool.state.refcount += 1
            log("ShmPoolState.refcount++ id=", pres.id, "refcount=", pool.state.refcount)

            buf_state = BufferState(
                pool=pool.state,
                offset=offset,
                width=width,
                height=height,
                stride=stride,
                format=format_,
            )
            buf = MyBufferResource(
                lib.wl_resource_get_client(pres._ptr),
                pres.version,
                id2,
                buf_state,
            )
            STATE.buffers[id2] = buf

        def resize(pres, size2):
            log("MyShmPoolResource.resize size=", size2)
            pool.state.mm.close()
            pool.state.mm = mmap.mmap(pool.state.fd, size2, access=mmap.ACCESS_READ)
            pool.state.size = size2

        def destroy_pool(pres):
            log("MyShmPoolResource.destroy id=", pres.id, "(mark destroyed; buffers may still hold refs)")
            pool.state.destroyed = True
            pool.state.maybe_cleanup()
            STATE.pools.pop(pres.id, None)
            # Do not call pres.destroy() — libwayland owns resource lifetime.

        pool.dispatcher["create_buffer"] = create_buffer
        pool.dispatcher["resize"] = resize
        pool.dispatcher["destroy"] = destroy_pool

    def release(res):
        log("wl_shm.release")

    resource.dispatcher["create_pool"] = create_pool
    resource.dispatcher["release"] = release


def bind_xdg_wm_base(resource):
    log("xdg_wm_base_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("xdg_wm_base", resource.id)] = resource
    STATE.xdg_wm_bases[resource.id] = resource

    def _on_destroy(res):
        """Called by libwayland resource_destroy_func on both explicit
        wl_resource.destroy requests AND forced cleanup at client disconnect.
        Null _ptr immediately so any subsequent Python call (e.g. ping()) raises
        an ensure_valid error instead of segfaulting on freed memory."""
        log("xdg_wm_base destroyed (client disconnect or explicit destroy) id=", res.id)
        res._ptr = None
        STATE.xdg_wm_bases.pop(res.id, None)
        STATE.bound_resources.pop(("xdg_wm_base", res.id), None)

    resource.dispatcher.destructor = _on_destroy

    def destroy(res):
        log("xdg_wm_base.destroy")
        STATE.xdg_wm_bases.pop(res.id, None)

    def create_positioner(res, id_):
        log("xdg_wm_base.create_positioner id=", id_, "(stubbed)")

    def get_xdg_surface(res, id_, surface):
        log("xdg_wm_base.get_xdg_surface id=", id_, "surface=", surface)
        xsurf = MyXdgSurfaceResource(lib.wl_resource_get_client(res._ptr), res.version, id_)
        STATE.xdg_surfaces[id_] = xsurf

        def get_toplevel(xres, id2):
            log("xdg_surface.get_toplevel id=", id2)
            top = MyXdgToplevelResource(lib.wl_resource_get_client(xres._ptr), xres.version, id2)
            STATE.xdg_toplevels[id2] = top

            def set_title(tres, title):
                log("xdg_toplevel.set_title", title)
                # Store title on the xdg_surface's associated wl_surface
                for sid, wlsurf in STATE.surfaces.items():
                    if STATE.xdg_surfaces.get(id_) is not None:
                        wlsurf.state.title = title
                        break

            def set_app_id(tres, app_id):
                log("xdg_toplevel.set_app_id", app_id)

            def destroy_toplevel(tres):
                log("xdg_toplevel.destroy")
                STATE.xdg_toplevels.pop(tres.id, None)
                # Do not call tres.destroy() — libwayland owns resource lifetime.

            top.dispatcher["set_title"] = set_title
            top.dispatcher["set_app_id"] = set_app_id
            top.dispatcher["destroy"] = destroy_toplevel

            # xdg-shell spec: xdg_toplevel.configure MUST be sent before xdg_surface.configure
            try:
                # xdg_toplevel.configure states must be a wl_array — pass as
                # bytes so pywayland marshals it correctly (list → unknown-size
                # void* → ValueError).
                top.configure(0, 0, b'')  # 0x0 = client picks size; states=[]
                log("xdg_toplevel.configure sent width=0 height=0 states=[]")
            except Exception as e:
                log("xdg_toplevel.configure failed:", repr(e))

            serial = STATE.next_serial()
            xsurf.configure(serial)
            log("xdg_surface.configure serial=", serial)

        def ack_configure(xres, serial):
            log("xdg_surface.ack_configure serial=", serial)

        def destroy_xdg_surface(xres):
            log("xdg_surface.destroy")
            STATE.xdg_surfaces.pop(xres.id, None)
            # Do not call xres.destroy() — libwayland owns resource lifetime.

        xsurf.dispatcher["get_toplevel"] = get_toplevel
        xsurf.dispatcher["ack_configure"] = ack_configure
        xsurf.dispatcher["destroy"] = destroy_xdg_surface

    def pong(res, serial):
        log("xdg_wm_base.pong serial=", serial)

    resource.dispatcher["destroy"] = destroy
    resource.dispatcher["create_positioner"] = create_positioner
    resource.dispatcher["get_xdg_surface"] = get_xdg_surface
    resource.dispatcher["pong"] = pong



WL_SEAT_CAPABILITY_POINTER  = 1
WL_SEAT_CAPABILITY_KEYBOARD = 2
WL_SEAT_CAPABILITY_TOUCH    = 4


def bind_wl_seat(resource):
    """Minimal wl_seat stub — advertises no input capabilities.

    Advertising capability=0 lets clients that require a seat proceed without
    us needing to implement wl_keyboard keymap or wl_pointer enter/leave events.
    When we later want to forward real input we can flip the capability flags
    and implement the per-device sub-resources.
    """
    log("wl_seat bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("wl_seat", resource.id)] = resource
    resource.dispatcher.destructor = lambda res: (
        setattr(res, '_ptr', None),
        STATE.bound_resources.pop(("wl_seat", res.id), None),
    )

    # Advertise no capabilities for now — clients will bind seat but won't
    # ask for keyboard/pointer/touch sub-resources.
    resource.capabilities(0)
    if resource.version >= 2:
        resource.name("warp-seat-0")

    def get_pointer(res, id_):
        log("wl_seat.get_pointer id=", id_, "(stub — no pointer capability advertised)")

    def get_keyboard(res, id_):
        log("wl_seat.get_keyboard id=", id_, "(stub — no keyboard capability advertised)")

    def get_touch(res, id_):
        log("wl_seat.get_touch id=", id_, "(stub — no touch capability advertised)")

    def release(res):
        log("wl_seat.release")

    resource.dispatcher["get_pointer"] = get_pointer
    resource.dispatcher["get_keyboard"] = get_keyboard
    resource.dispatcher["get_touch"] = get_touch
    resource.dispatcher["release"] = release


def bind_wl_output(resource):
    """Minimal wl_output stub — 1920x1080@60 virtual display."""
    log("wl_output bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("wl_output", resource.id)] = resource
    resource.dispatcher.destructor = lambda res: (
        setattr(res, '_ptr', None),
        STATE.bound_resources.pop(("wl_output", res.id), None),
    )

    # geometry: x, y, physical_width_mm, physical_height_mm,
    #           subpixel (0=unknown), make, model, transform (0=normal)
    resource.geometry(0, 0, 527, 297, 0, "Warp", "Virtual-1", 0)
    # mode: flags (1=current, 2=preferred → 3 = both), width, height, refresh_mHz
    resource.mode(0x3, 256, 256, 60000)
    if resource.version >= 2:
        resource.scale(1)
        resource.done()


def bind_linux_dmabuf(resource):
    log("linux_dmabuf_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    _register_resource(resource)
    STATE.bound_resources[("zwp_linux_dmabuf_v1", resource.id)] = resource
    resource.dispatcher.destructor = lambda res: (
        setattr(res, '_ptr', None),
        STATE.bound_resources.pop(("zwp_linux_dmabuf_v1", res.id), None),
    )

    try:
        resource.format(DRM_FORMAT_XRGB8888)
        resource.format(DRM_FORMAT_ARGB8888)
        log("linux_dmabuf.format advertised XRGB8888/ARGB8888")
    except Exception as e:
        log("linux_dmabuf.format failed:", repr(e))

    try:
        resource.modifier(DRM_FORMAT_XRGB8888, DRM_FORMAT_MOD_LINEAR_HI, DRM_FORMAT_MOD_LINEAR_LO)
        resource.modifier(DRM_FORMAT_ARGB8888, DRM_FORMAT_MOD_LINEAR_HI, DRM_FORMAT_MOD_LINEAR_LO)
        log("linux_dmabuf.modifier advertised XRGB8888/ARGB8888 linear")
    except Exception as e:
        log("linux_dmabuf.modifier failed:", repr(e))

    def destroy_dmabuf(res):
        log("zwp_linux_dmabuf_v1.destroy")

    def create_params(res, params_id):
        log("zwp_linux_dmabuf_v1.create_params params_id=", params_id)
        params = ZwpLinuxBufferParamsV1.resource_class(
            lib.wl_resource_get_client(res._ptr),
            res.version,
            params_id,
        )
        # Register so pywayland can look this resource up if passed as Object arg.
        if params._ptr:
            params.interface.registry[params._ptr] = params
        DMABUF_PARAMS[params_id] = {
            "resource": params,
            "planes": [],
        }

        def destroy_params(pres):
            log("zwp_linux_buffer_params_v1.destroy id=", pres.id)
            DMABUF_PARAMS.pop(pres.id, None)
            # Do not call pres.destroy() — libwayland owns resource lifetime.

        def add_plane(pres, fd, plane_idx, offset, stride, modifier_hi, modifier_lo):
            log(
                "zwp_linux_buffer_params_v1.add",
                "id=", pres.id,
                "fd=", fd,
                "plane_idx=", plane_idx,
                "offset=", offset,
                "stride=", stride,
                "modifier_hi=", modifier_hi,
                "modifier_lo=", modifier_lo,
            )
            entry = DMABUF_PARAMS.setdefault(pres.id, {"resource": pres, "planes": []})
            entry["planes"].append(
                {
                    "fd": fd,
                    "plane_idx": plane_idx,
                    "offset": offset,
                    "stride": stride,
                    "modifier_hi": modifier_hi,
                    "modifier_lo": modifier_lo,
                }
            )

        def create_buffer_from_params(pres, width, height, format_, flags):
            log(
                "zwp_linux_buffer_params_v1.create",
                "id=", pres.id,
                "width=", width,
                "height=", height,
                "format=", format_,
                "flags=", flags,
            )

            entry = DMABUF_PARAMS.get(pres.id, {})
            planes = sorted(entry.get("planes", []), key=lambda p: p["plane_idx"])

            if not planes:
                log("zwp_linux_buffer_params_v1.create: no planes recorded")
                try:
                    pres.failed()
                    log("zwp_linux_buffer_params_v1.failed sent import_ok= False")
                except Exception as e:
                    log("zwp_linux_buffer_params_v1.failed send failed:", repr(e))
                return

            if len(planes) != 1:
                log(
                    "zwp_linux_buffer_params_v1.create: multi-plane import not implemented yet, planes=",
                    len(planes),
                )
                try:
                    pres.failed()
                    log("zwp_linux_buffer_params_v1.failed sent import_ok= False")
                except Exception as e:
                    log("zwp_linux_buffer_params_v1.failed send failed:", repr(e))
                return

            plane0 = planes[0]
            modifier = ((plane0["modifier_hi"] & 0xFFFFFFFF) << 32) | (plane0["modifier_lo"] & 0xFFFFFFFF)

            owned_planes = []
            for p in planes:
                owned = dict(p)
                owned["fd"] = os.dup(p["fd"])
                owned_planes.append(owned)

            buf_state = DmabufBufferState(
                width=width,
                height=height,
                format=format_,
                modifier=modifier,
                planes=owned_planes,
                egl_image=None,
            )

            client = lib.wl_resource_get_client(pres._ptr)
            buf = MyBufferResource(client, 1, 0, buf_state)
            log(
                "created compositor dmabuf buffer resource",
                "buf.id=", buf.id,
                "buf=", buf,
                "buf._ptr=", getattr(buf, "_ptr", None),
            )

            def destroy_buffer(bres):
                log("wl_buffer.destroy request id=", bres.id)
                # Do not call bres.destroy() — libwayland owns resource lifetime.

            buf.dispatcher["destroy"] = destroy_buffer

            try:
                log(
                    "about to send zwp_linux_buffer_params_v1.created",
                    "params_id=", pres.id,
                    "buffer_id=", buf.id,
                    "buffer_obj=", buf,
                    "buffer_ptr=", getattr(buf, "_ptr", None),
                )
                args = ffi.new("union wl_argument[1]")
                args[0].o = ffi.cast("struct wl_object *", buf._ptr)
                lib.wl_resource_post_event_array(pres._ptr, 0, args)
                log("zwp_linux_buffer_params_v1.created sent", "params_id=", pres.id, "buffer_id=", buf.id)
            except Exception as e:
                log("zwp_linux_buffer_params_v1.created send failed:", repr(e))
                try:
                    buf.destroy()
                except Exception:
                    pass
                try:
                    pres.failed()
                    log("zwp_linux_buffer_params_v1.failed sent import_ok= False")
                except Exception as e2:
                    log("zwp_linux_buffer_params_v1.failed send failed:", repr(e2))

        def create_immed(pres, buffer_id, width, height, format_, flags):
            log(
                "zwp_linux_buffer_params_v1.create_immed",
                "id=", pres.id,
                "buffer_id=", buffer_id,
                "width=", width,
                "height=", height,
                "format=", format_,
                "flags=", flags,
            )

            entry = DMABUF_PARAMS.get(pres.id, {})
            planes = sorted(entry.get("planes", []), key=lambda p: p["plane_idx"])

            if not planes:
                log("zwp_linux_buffer_params_v1.create_immed: no planes recorded")
                try:
                    pres.failed()
                    log("zwp_linux_buffer_params_v1.failed sent for create_immed import_ok= False")
                except Exception as e:
                    log("zwp_linux_buffer_params_v1.failed send failed:", repr(e))
                return

            if len(planes) != 1:
                log(
                    "zwp_linux_buffer_params_v1.create_immed: multi-plane import not implemented yet, planes=",
                    len(planes),
                )
                try:
                    pres.failed()
                    log("zwp_linux_buffer_params_v1.failed sent for create_immed import_ok= False")
                except Exception as e:
                    log("zwp_linux_buffer_params_v1.failed send failed:", repr(e))
                return

            plane0 = planes[0]
            modifier = ((plane0["modifier_hi"] & 0xFFFFFFFF) << 32) | (plane0["modifier_lo"] & 0xFFFFFFFF)

            owned_planes = []
            for p in planes:
                owned = dict(p)
                owned["fd"] = os.dup(p["fd"])
                owned_planes.append(owned)

            buf_state = DmabufBufferState(
                width=width,
                height=height,
                format=format_,
                modifier=modifier,
                planes=owned_planes,
                egl_image=None,
            )

            client = lib.wl_resource_get_client(pres._ptr)
            buf = MyBufferResource(client, 1, buffer_id, buf_state)
            log(
                "zwp_linux_buffer_params_v1.create_immed created buffer",
                "params_id=", pres.id,
                "buffer_id=", buf.id,
                "buf=", buf,
                "buf._ptr=", getattr(buf, "_ptr", None),
            )

            def destroy_buffer(bres):
                log("wl_buffer.destroy request id=", bres.id)
                # Do not call bres.destroy() — libwayland owns resource lifetime.

            buf.dispatcher["destroy"] = destroy_buffer

        params.dispatcher["destroy"] = destroy_params
        params.dispatcher["add"] = add_plane
        params.dispatcher["create"] = create_buffer_from_params
        params.dispatcher["create_immed"] = create_immed

    resource.dispatcher["destroy"] = destroy_dmabuf
    resource.dispatcher["create_params"] = create_params


class ShmPreviewBridge:
    def __init__(self):
        self.display = None

    def setup(self):
        log("[moksha-warp] starting up")

        # Reset mutable module-level state so a re-setup in the same process
        # (e.g. during testing) does not inherit stale resources.
        global DMABUF_PARAMS
        DMABUF_PARAMS.clear()
        STATE.buffers.clear()
        STATE.surfaces.clear()
        STATE.pools.clear()
        STATE.callbacks.clear()
        STATE.xdg_surfaces.clear()
        STATE.xdg_toplevels.clear()
        STATE.xdg_wm_bases.clear()
        STATE.bound_resources.clear()
        STATE.server_globals.clear()
        STATE.globals.clear()
        STATE.serial = 1
        STATE.last_ping_time = 0.0
        log("[setup] module state reset")

        self.display = Display()
        log("Display created:", self.display is not None)

        socket_name = self.display.add_socket("wayland-warp")
        if isinstance(socket_name, bytes):
            socket_name = socket_name.decode()
        STATE.socket_name = socket_name

        log("Socket created:", socket_name is not None)
        log("Socket name:", socket_name)
        log("XDG_RUNTIME_DIR:", os.environ.get("XDG_RUNTIME_DIR"))

        # GLES renderer must be initialized before EGL importer so that
        # both share the same EGL display (required by eglCreateImageKHR).
        global DMABUF_GL_RENDERER, EGL_DMABUF_IMPORTER
        try:
            DMABUF_GL_RENDERER = GlesDmabufRenderer((256, 256)).initialize()
            GLES_BACKEND.set_gles_renderer(DMABUF_GL_RENDERER)
            log("[gles] GLES renderer initialized")
        except Exception as e:
            DMABUF_GL_RENDERER = None
            log("[gles] GLES renderer init failed:", repr(e))

        try:
            importer = EglDmabufImporter()
            if DMABUF_GL_RENDERER is not None:
                # Share the EGL display that SDL/GLES just made current.
                egl_dpy = DMABUF_GL_RENDERER.get_egl_display()
                importer.initialize_with_display(egl_dpy)
                log(
                    "[egl] importer initialized with shared display:",
                    egl_dpy,
                    f"EGL {importer.major}.{importer.minor}",
                    "import_ext=", importer.has_extension("EGL_EXT_image_dma_buf_import"),
                )
            else:
                # Fallback: no renderer yet, use the default display.
                # eglCreateImageKHR may fail if no context is current.
                log("[egl] warning: no GLES renderer — using default EGL display")
                importer.initialize()
                log(
                    "[egl] importer initialized (no shared context):",
                    f"EGL {importer.major}.{importer.minor}",
                )
            EGL_DMABUF_IMPORTER = importer
            log(
                "[egl] EGL_EXT_image_dma_buf_import:",
                importer.has_extension("EGL_EXT_image_dma_buf_import"),
            )
            log(
                "[egl] EGL_EXT_image_dma_buf_import_modifiers:",
                importer.has_extension("EGL_EXT_image_dma_buf_import_modifiers"),
            )
            if not importer.has_extension("EGL_EXT_image_dma_buf_import"):
                log("[egl] WARNING: dmabuf import extension not available — "
                    "eglCreateImageKHR will fail for dma-buf buffers")
        except Exception as e:
            EGL_DMABUF_IMPORTER = None
            log("[egl] importer init failed:", repr(e))

        global KMS_BACKEND
        try:
            KMS_BACKEND = KmsDirectBackend(logger=log)
            log("[kms-probe] backend ready, candidate:", getattr(KMS_BACKEND._candidate, "path", None))
        except Exception as e:
            KMS_BACKEND = None
            log("[kms-probe] backend init failed:", repr(e))

        compositor_global = WlCompositor.global_class(self.display, version=4)
        compositor_global.bind_func = bind_wl_compositor
        STATE.server_globals.append(compositor_global)
        STATE.globals.append("wl_compositor")

        shm_global = WlShm.global_class(self.display, version=1)
        shm_global.bind_func = bind_wl_shm
        STATE.server_globals.append(shm_global)
        STATE.globals.append("wl_shm")

        xdg_global = XdgWmBase.global_class(self.display, version=1)
        xdg_global.bind_func = bind_xdg_wm_base
        STATE.server_globals.append(xdg_global)
        STATE.globals.append("xdg_wm_base")

        dmabuf_global = ZwpLinuxDmabufV1.global_class(self.display, version=3)
        dmabuf_global.bind_func = bind_linux_dmabuf
        STATE.server_globals.append(dmabuf_global)
        STATE.globals.append("zwp_linux_dmabuf_v1")

        seat_global = WlSeat.global_class(self.display, version=5)
        seat_global.bind_func = bind_wl_seat
        STATE.server_globals.append(seat_global)
        STATE.globals.append("wl_seat")

        output_global = WlOutput.global_class(self.display, version=3)
        output_global.bind_func = bind_wl_output
        STATE.server_globals.append(output_global)
        STATE.globals.append("wl_output")

        log("Globals:")
        for g in STATE.globals:
            log(" ", g)

        save_report()
        log("")
        log("Run weston-simple-egl against socket:", socket_name)
        log(f"WAYLAND_DISPLAY={socket_name} weston-simple-egl")
        log("")

    def run(self):
        if self.display is None:
            self.setup()

        def _shutdown(signum, frame):
            raise SystemExit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        event_loop = self.display.get_event_loop()

        while True:
            # Drain SDL events from whichever window is active.
            # DMABUF_GL_RENDERER is the GLES preview window (primary path).
            # RENDERER is the legacy SHM pygame window (fallback / SHM clients).
            if DMABUF_GL_RENDERER is not None and DMABUF_GL_RENDERER.ready:
                DMABUF_GL_RENDERER.pump_events()
            else:
                RENDERER.pump()
            self.display.flush_clients()
            event_loop.dispatch(0)

            # Periodic compositor-side ping to all active xdg_wm_base clients.
            # Clients that miss pong are logged but not disconnected (for now).
            now = time.monotonic()
            if now - STATE.last_ping_time > 5.0 and STATE.xdg_wm_bases:
                serial = STATE.next_serial()
                for xwm in list(STATE.xdg_wm_bases.values()):
                    try:
                        xwm.ping(serial)
                        log("xdg_wm_base.ping serial=", serial, "id=", getattr(xwm, "id", "?"))
                    except Exception as e:
                        log("xdg_wm_base.ping failed:", repr(e))
                STATE.last_ping_time = now

            time.sleep(0.005)


def _shutdown_resources() -> None:
    """Tear down GPU/EGL resources and the Wayland display on exit.

    Called from main() after the run loop exits.  Safe to call even if
    setup() partially failed (all objects guard against None).
    """
    # Destroy the Wayland display — closes the socket and frees all resources
    global DMABUF_GL_RENDERER, EGL_DMABUF_IMPORTER

    importer = EGL_DMABUF_IMPORTER
    EGL_DMABUF_IMPORTER = None
    if importer is not None:
        try:
            importer.terminate()
            log("[shutdown] EGL importer terminated")
        except Exception as exc:
            log("[shutdown] EGL importer terminate error:", repr(exc))

    renderer = DMABUF_GL_RENDERER
    DMABUF_GL_RENDERER = None
    if renderer is not None and renderer.ready:
        try:
            import pygame
            pygame.display.quit()
            pygame.quit()
            log("[shutdown] pygame/SDL display closed")
        except Exception as exc:
            log("[shutdown] pygame quit error:", repr(exc))

    log("[shutdown] cleanup done")


def main():
    bridge = ShmPreviewBridge()
    try:
        bridge.setup()
        bridge.run()
    except SystemExit:
        log("Exiting cleanly.")
    except KeyboardInterrupt:
        log("Interrupted.")
    except Exception as e:
        log("Fatal error:", repr(e))
        raise
    finally:
        try:
            if bridge.display is not None:
                bridge.display.destroy()
                log("[shutdown] Wayland display destroyed")
        except Exception as exc:
            log("[shutdown] display.destroy() error:", repr(exc))
        _shutdown_resources()


if __name__ == "__main__":
    main()
