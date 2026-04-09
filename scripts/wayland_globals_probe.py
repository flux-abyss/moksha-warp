#!/usr/bin/env python3
import os
import sys
import json
import time
import mmap
import signal

import pygame
from pywayland import ffi, lib

from pywayland.server import Display
from pywayland.protocol.wayland import (
    WlCompositor,
    WlSurface,
    WlShm,
    WlShmPool,
    WlBuffer,
    WlCallback,
)
from pywayland.protocol.xdg_shell import (
    XdgWmBase,
    XdgSurface,
    XdgToplevel,
)

LOG_PATH = os.path.expanduser("~/repos/moksha-warp/logs/wayland_globals_probe.json")


def log(msg, *args):
    if args:
        print(msg, *args, flush=True)
    else:
        print(msg, flush=True)


class ProbeState:
    def __init__(self):
        self.globals = []
        self.buffers = {}
        self.surfaces = {}
        self.pools = {}
        self.bound_resources = {}
        self.callbacks = {}
        self.xdg_surfaces = {}
        self.xdg_toplevels = {}
        self.server_globals = []
        self.serial = 1
        self.socket_name = None

    def next_serial(self):
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

    def ensure_window(self, width, height):
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

    def present_buffer(self, buf_state):
        if buf_state.format != 0:
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

        raw = memoryview(mm)[offset:offset + total_bytes]
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
                packed[dst_start:dst_start + expected_row_bytes] = raw[src_start:src_end]
            surf = pygame.image.frombuffer(packed, (width, height), "BGRA")
            self.screen.blit(surf, (0, 0))

        pygame.display.flip()
        log(
            f"[renderer] presented buffer "
            f"{width}x{height} stride={stride} offset={offset} fmt={buf_state.format}"
        )


RENDERER = PygameRenderer()


class ShmPoolState:
    def __init__(self, fd, size, mm):
        self.fd = fd
        self.size = size
        self.mm = mm


class BufferState:
    def __init__(self, pool, offset, width, height, stride, fmt):
        self.pool = pool
        self.offset = offset
        self.width = width
        self.height = height
        self.stride = stride
        self.format = fmt


class SurfaceState:
    def __init__(self):
        self.pending_buffer = None
        self.current_buffer = None
        self.frame_callbacks = []


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
        log("MyCallbackResource.__init__ id=", id_)


class MyBufferResource(WlBuffer.resource_class):
    def __init__(self, client, version, id_, state):
        super().__init__(client, version, id_)
        self.state = state
        STATE.buffers[id_] = self
        log("MyBufferResource.__init__ id=", id_)

    def destroy(self):
        log("MyBufferResource.destroy id=", self.id)
        STATE.buffers.pop(self.id, None)
        super().destroy()


class MyShmPoolResource(WlShmPool.resource_class):
    def __init__(self, client, version, id_, fd, size):
        super().__init__(client, version, id_)
        dup_fd = os.dup(fd)
        mm = mmap.mmap(dup_fd, size, access=mmap.ACCESS_READ)
        self.state = ShmPoolState(dup_fd, size, mm)
        STATE.pools[id_] = self
        log("MyShmPoolResource.__init__ client=", client, "version=", version, "id=", id_, "fd=", dup_fd, "size=", size)

    def create_buffer(self, id, offset, width, height, stride, format):
        log(
            "MyShmPoolResource.create_buffer",
            f"id={id}",
            f"offset={offset}",
            f"width={width}",
            f"height={height}",
            f"stride={stride}",
            f"format={format}",
        )
        buf_state = BufferState(
            pool=self.state,
            offset=offset,
            width=width,
            height=height,
            stride=stride,
            fmt=format,
        )
        MyBufferResource(self._client, self._version, id, buf_state)

    def resize(self, size):
        log("MyShmPoolResource.resize size=", size)
        self.state.mm.close()
        self.state.mm = mmap.mmap(self.state.fd, size, access=mmap.ACCESS_READ)
        self.state.size = size

    def destroy(self):
        log("MyShmPoolResource.destroy id=", self.id, "(resource only; keeping mmap/fd alive)")
        STATE.pools.pop(self.id, None)
        super().destroy()


class MyShmResource(WlShm.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        log("MyShmResource.__init__ client=", client, "version=", version, "id=", id_)

        # WL_SHM_FORMAT_ARGB8888
        self.format(0)

    def create_pool(self, id, fd, size):
        log("shm.create_pool id=", id, "fd=", fd, "size=", size)
        MyShmPoolResource(self._client, self._version, id, fd, size)

    def release(self):
        log("MyShmResource.release id=", self.id)
        super().destroy()


class MyWlSurfaceResource(WlSurface.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        self.state = SurfaceState()
        STATE.surfaces[id_] = self
        log("MyWlSurfaceResource.__init__ id=", id_)

    def attach(self, buffer, x, y):
        log("wl_surface.attach buffer=", buffer, "x=", x, "y=", y)
        if buffer is None:
            self.state.pending_buffer = None
            return

        try:
            self.state.pending_buffer = buffer.state
        except AttributeError:
            log("wl_surface.attach: buffer has no .state")
            self.state.pending_buffer = None

    def damage(self, x, y, width, height):
        log("wl_surface.damage x=", x, "y=", y, "w=", width, "h=", height)

    def frame(self, callback):
        log("wl_surface.frame callback=", callback)
        self.state.frame_callbacks.append(callback)

    def commit(self):
        log("wl_surface.commit")
        self.state.current_buffer = self.state.pending_buffer

        if self.state.current_buffer is not None:
            try:
                RENDERER.present_buffer(self.state.current_buffer)
            except Exception as e:
                log("present_buffer failed:", repr(e))

        callbacks = self.state.frame_callbacks[:]
        self.state.frame_callbacks.clear()
        now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
        for cb in callbacks:
            try:
                cb.done(now_ms)
            except Exception as e:
                log("frame callback done failed:", repr(e))

    def destroy(self):
        log("wl_surface.destroy id=", self.id)
        STATE.surfaces.pop(self.id, None)
        super().destroy()


class MyWlCompositorResource(WlCompositor.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        log("MyWlCompositorResource.__init__ id=", id_)

    def create_surface(self, id):
        log("wl_compositor.create_surface id=", id)
        MyWlSurfaceResource(self._client, self._version, id)

    def create_region(self, id):
        log("wl_compositor.create_region id=", id, "(stubbed)")
        # Some clients may ask for a region. We are ignoring it for now.


class MyXdgToplevelResource(XdgToplevel.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        log("MyXdgToplevelResource.__init__ id=", id_)

    def destroy(self):
        log("xdg_toplevel.destroy id=", self.id)
        super().destroy()

    def set_title(self, title):
        log("xdg_toplevel.set_title", title)

    def set_app_id(self, app_id):
        log("xdg_toplevel.set_app_id", app_id)

    def move(self, seat, serial):
        log("xdg_toplevel.move seat=", seat, "serial=", serial)

    def resize(self, seat, serial, edges):
        log("xdg_toplevel.resize seat=", seat, "serial=", serial, "edges=", edges)

    def set_max_size(self, width, height):
        log("xdg_toplevel.set_max_size", width, height)

    def set_min_size(self, width, height):
        log("xdg_toplevel.set_min_size", width, height)

    def set_maximized(self):
        log("xdg_toplevel.set_maximized")

    def unset_maximized(self):
        log("xdg_toplevel.unset_maximized")

    def set_fullscreen(self, output):
        log("xdg_toplevel.set_fullscreen output=", output)

    def unset_fullscreen(self):
        log("xdg_toplevel.unset_fullscreen")

    def set_minimized(self):
        log("xdg_toplevel.set_minimized")


class MyXdgSurfaceResource(XdgSurface.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        self.last_configure = None
        log("MyXdgSurfaceResource.__init__ id=", id_)

    def get_toplevel(self, id):
        log("xdg_surface.get_toplevel id=", id)
        MyXdgToplevelResource(self._client, self._version, id)
        serial = STATE.next_serial()
        self.last_configure = serial
        self.configure(serial)
        log("xdg_surface.configure serial=", serial)

    def ack_configure(self, serial):
        log("xdg_surface.ack_configure serial=", serial)

    def destroy(self):
        log("xdg_surface.destroy id=", self.id)
        super().destroy()


class MyXdgWmBaseResource(XdgWmBase.resource_class):
    def __init__(self, client, version, id_):
        super().__init__(client, version, id_)
        log("MyXdgWmBaseResource.__init__ id=", id_)

    def destroy(self):
        log("xdg_wm_base.destroy id=", self.id)
        super().destroy()

    def create_positioner(self, id):
        log("xdg_wm_base.create_positioner id=", id, "(stubbed)")

    def get_xdg_surface(self, id, surface):
        log("xdg_wm_base.get_xdg_surface id=", id, "surface=", surface)
        MyXdgSurfaceResource(self._client, self._version, id)

    def pong(self, serial):
        log("xdg_wm_base.pong serial=", serial)



def compositor_bind(resource):
    log("compositor_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    STATE.bound_resources[("wl_compositor", resource.id)] = resource

    def create_surface(res, id_):
        log("wl_compositor.create_surface id=", id_)
        surf = MyWlSurfaceResource(lib.wl_resource_get_client(res._ptr), res.version, id_)
        STATE.surfaces[id_] = surf

        def destroy_surface(sres):
            log("wl_surface.destroy id=", sres.id)
            STATE.surfaces.pop(sres.id, None)
            sres.destroy()

        def attach(sres, buffer, x, y):
            log("wl_surface.attach buffer=", buffer, "x=", x, "y=", y)
            if buffer is None:
                surf.state.pending_buffer = None
            else:
                try:
                    surf.state.pending_buffer = buffer.state
                except AttributeError:
                    log("wl_surface.attach: buffer has no .state")
                    surf.state.pending_buffer = None

        def damage(sres, x, y, width, height):
            log("wl_surface.damage x=", x, "y=", y, "w=", width, "h=", height)

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
            log("wl_surface.commit")
            surf.state.current_buffer = surf.state.pending_buffer

            if surf.state.current_buffer is not None:
                try:
                    RENDERER.present_buffer(surf.state.current_buffer)
                except Exception as e:
                    log("present_buffer failed:", repr(e))

            callbacks = surf.state.frame_callbacks[:]
            surf.state.frame_callbacks.clear()
            now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
            for cb in callbacks:
                try:
                    cb.done(now_ms)
                except Exception as e:
                    log("frame callback done failed:", repr(e))
                try:
                    STATE.callbacks.pop(cb.id, None)
                except Exception:
                    pass
                try:
                    cb.destroy()
                except Exception as e:
                    log("frame callback destroy failed:", repr(e))

        def set_opaque_region(sres, region):
            log("wl_surface.set_opaque_region region=", region)

        def set_input_region(sres, region):
            log("wl_surface.set_input_region region=", region)

        def set_buffer_transform(sres, transform):
            log("wl_surface.set_buffer_transform transform=", transform)

        def set_buffer_scale(sres, scale):
            log("wl_surface.set_buffer_scale scale=", scale)

        def damage_buffer(sres, x, y, width, height):
            log("wl_surface.damage_buffer x=", x, "y=", y, "w=", width, "h=", height)

        surf.dispatcher["destroy"] = destroy_surface
        surf.dispatcher["attach"] = attach
        surf.dispatcher["damage"] = damage
        surf.dispatcher["frame"] = frame
        surf.dispatcher["set_opaque_region"] = set_opaque_region
        surf.dispatcher["set_input_region"] = set_input_region
        surf.dispatcher["commit"] = commit
        if "set_buffer_transform" in [m.name for m in surf.dispatcher.messages]:
            surf.dispatcher["set_buffer_transform"] = set_buffer_transform
        if "set_buffer_scale" in [m.name for m in surf.dispatcher.messages]:
            surf.dispatcher["set_buffer_scale"] = set_buffer_scale
        if "damage_buffer" in [m.name for m in surf.dispatcher.messages]:
            surf.dispatcher["damage_buffer"] = damage_buffer

    def create_region(res, id_):
        log("wl_compositor.create_region id=", id_, "(stubbed)")
        # Region not implemented yet.

    resource.dispatcher["create_surface"] = create_surface
    resource.dispatcher["create_region"] = create_region


def shm_bind(resource):
    log("shm_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    STATE.bound_resources[("wl_shm", resource.id)] = resource

    try:
        resource.format(0)
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
            buf_state = BufferState(
                pool=pool.state,
                offset=offset,
                width=width,
                height=height,
                stride=stride,
                fmt=format_,
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
            log("MyShmPoolResource.destroy id=", pres.id, "(keeping mmap/fd alive for buffers)")
            STATE.pools.pop(pres.id, None)
            pres.destroy()

        pool.dispatcher["create_buffer"] = create_buffer
        pool.dispatcher["resize"] = resize
        pool.dispatcher["destroy"] = destroy_pool

    def release(res):
        log("wl_shm.release")

    resource.dispatcher["create_pool"] = create_pool
    resource.dispatcher["release"] = release


def xdg_wm_base_bind(resource):
    log("xdg_wm_base_bind resource=", resource, "version=", resource.version, "id=", resource.id)
    STATE.bound_resources[("xdg_wm_base", resource.id)] = resource

    def destroy(res):
        log("xdg_wm_base.destroy")

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

            def set_app_id(tres, app_id):
                log("xdg_toplevel.set_app_id", app_id)

            def destroy_toplevel(tres):
                log("xdg_toplevel.destroy")

            top.dispatcher["set_title"] = set_title
            top.dispatcher["set_app_id"] = set_app_id
            top.dispatcher["destroy"] = destroy_toplevel

            serial = STATE.next_serial()
            xsurf.configure(serial)
            log("xdg_surface.configure serial=", serial)

        def ack_configure(xres, serial):
            log("xdg_surface.ack_configure serial=", serial)

        def destroy_xdg_surface(xres):
            log("xdg_surface.destroy")

        xsurf.dispatcher["get_toplevel"] = get_toplevel
        xsurf.dispatcher["ack_configure"] = ack_configure
        xsurf.dispatcher["destroy"] = destroy_xdg_surface

    def pong(res, serial):
        log("xdg_wm_base.pong serial=", serial)

    resource.dispatcher["destroy"] = destroy
    resource.dispatcher["create_positioner"] = create_positioner
    resource.dispatcher["get_xdg_surface"] = get_xdg_surface
    resource.dispatcher["pong"] = pong

def main():
    log("=== Moksha-Warp Wayland Globals Probe ===")

    display = Display()
    log("Display created:", display is not None)

    socket_name = display.add_socket(None)
    if isinstance(socket_name, bytes):
        socket_name = socket_name.decode()
    STATE.socket_name = socket_name
    log("Socket created:", socket_name is not None)
    log("Socket name:", socket_name)
    log("XDG_RUNTIME_DIR:", os.environ.get("XDG_RUNTIME_DIR"))

    compositor_global = WlCompositor.global_class(display, version=4)
    compositor_global.bind_func = compositor_bind
    STATE.server_globals.append(compositor_global)
    STATE.globals.append("wl_compositor")

    shm_global = WlShm.global_class(display, version=1)
    shm_global.bind_func = shm_bind
    STATE.server_globals.append(shm_global)
    STATE.globals.append("wl_shm")

    xdg_global = XdgWmBase.global_class(display, version=1)
    xdg_global.bind_func = xdg_wm_base_bind
    STATE.server_globals.append(xdg_global)
    STATE.globals.append("xdg_wm_base")

    log("Globals:")
    for g in STATE.globals:
        log(" ", g)

    save_report()

    log("")
    log("Run weston-simple-egl against socket:", socket_name)
    log(f"WAYLAND_DISPLAY={socket_name} weston-simple-egl")
    log("")

    def _shutdown(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    event_loop = display.get_event_loop()

    while True:
        RENDERER.pump()
        display.flush_clients()
        event_loop.dispatch(0)
        time.sleep(0.005)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        log("Exiting cleanly.")
    except KeyboardInterrupt:
        log("Interrupted.")
    except Exception as e:
        log("Fatal error:", repr(e))
        raise
