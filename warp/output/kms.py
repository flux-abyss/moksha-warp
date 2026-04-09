# KMS/DRM device probe and output backend seam.
# GlesPreviewBackend — SDL/GLES preview (current working path).
# KmsDirectBackend  — real DRM device probe; drmModeSetCrtc not yet wired.

from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import glob
import os
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Typed exception for scanout refusal
# ---------------------------------------------------------------------------

class DirectScanoutError(RuntimeError):
    """Raised by KmsDirectBackend when direct presentation cannot proceed."""


# ---------------------------------------------------------------------------
# DRM ctypes bindings — just enough for device probe/enumeration
# ---------------------------------------------------------------------------

def _load_libdrm() -> Optional[ctypes.CDLL]:
    path = ctypes.util.find_library("drm")
    if not path:
        return None
    try:
        return ctypes.CDLL(path)
    except OSError:
        return None


_libdrm: Optional[ctypes.CDLL] = _load_libdrm()


# drmModeRes – trimmed to the fields we actually read
class _DrmModeRes(ctypes.Structure):
    _fields_ = [
        ("count_fbs",         ctypes.c_int),
        ("fbs",               ctypes.c_void_p),
        ("count_crtcs",       ctypes.c_int),
        ("crtcs",             ctypes.c_void_p),
        ("count_connectors",  ctypes.c_int),
        ("connectors",        ctypes.POINTER(ctypes.c_uint32)),
        ("count_encoders",    ctypes.c_int),
        ("encoders",          ctypes.c_void_p),
        ("min_width",         ctypes.c_uint32),
        ("max_width",         ctypes.c_uint32),
        ("min_height",        ctypes.c_uint32),
        ("max_height",        ctypes.c_uint32),
    ]


# drmModeModeInfo
class _DrmModeModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock",       ctypes.c_uint32),
        ("hdisplay",    ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end",   ctypes.c_uint16),
        ("htotal",      ctypes.c_uint16),
        ("hskew",       ctypes.c_uint16),
        ("vdisplay",    ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end",   ctypes.c_uint16),
        ("vtotal",      ctypes.c_uint16),
        ("vscan",       ctypes.c_uint16),
        ("vrefresh",    ctypes.c_uint32),
        ("flags",       ctypes.c_uint32),
        ("type",        ctypes.c_uint32),
        ("name",        ctypes.c_char * 32),
    ]


# drmModeConnector – trimmed; we only need connection status + modes + geometry
class _DrmModeConnector(ctypes.Structure):
    _fields_ = [
        ("connector_id",      ctypes.c_uint32),
        ("encoder_id",        ctypes.c_uint32),
        ("connector_type",    ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection",        ctypes.c_uint32),   # 1=connected, 2=disconnected, 3=unknown
        ("mmWidth",           ctypes.c_uint32),
        ("mmHeight",          ctypes.c_uint32),
        ("subpixel",          ctypes.c_uint32),
        ("count_modes",       ctypes.c_int),
        ("modes",             ctypes.POINTER(_DrmModeModeInfo)),
        ("count_props",       ctypes.c_int),
        ("props",             ctypes.c_void_p),
        ("prop_values",       ctypes.c_void_p),
        ("count_encoders",    ctypes.c_int),
        ("encoders",          ctypes.c_void_p),
    ]


# Numeric → human-readable connector type name
_CONNECTOR_NAMES = {
    0: "Unknown", 1: "VGA", 2: "DVI-I", 3: "DVI-D", 4: "DVI-A",
    5: "Composite", 6: "SVIDEO", 7: "LVDS", 8: "Component",
    9: "DIN", 10: "DisplayPort", 11: "HDMI-A", 12: "HDMI-B",
    13: "TV", 14: "eDP", 15: "Virtual", 16: "DSI", 17: "DPI",
    18: "Writeback", 19: "SPI",
}

_DRM_MODE_CONNECTED    = 1
_DRM_MODE_DISCONNECTED = 2

# GEM handle close — used after drmModeAddFB2 test to release the imported handle.
# DRM_IOCTL_GEM_CLOSE = DRM_IOW(0x09, struct drm_gem_close) where struct is 8 bytes.
# On Linux/amd64: 0x40000000 | (8 << 16) | (0x64 << 8) | 0x09 = 0x40086409
_DRM_IOCTL_GEM_CLOSE = 0x40086409


class _DrmGemClose(ctypes.Structure):
    _fields_ = [
        ("handle", ctypes.c_uint32),
        ("pad",    ctypes.c_uint32),
    ]


# drmModeEncoder — we only need crtc_id
class _DrmModeEncoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id",     ctypes.c_uint32),
        ("encoder_type",   ctypes.c_uint32),
        ("crtc_id",        ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones",ctypes.c_uint32),
    ]


# drmModeCrtc — we need the embedded mode for restoration
class _DrmModeCrtc(ctypes.Structure):
    _fields_ = [
        ("crtc_id",   ctypes.c_uint32),
        ("buffer_id", ctypes.c_uint32),
        ("x",         ctypes.c_uint32),
        ("y",         ctypes.c_uint32),
        ("width",     ctypes.c_uint32),
        ("height",    ctypes.c_uint32),
        ("mode_valid",ctypes.c_int),
        ("mode",      _DrmModeModeInfo),   # 68-byte embedded struct
        ("gamma_size",ctypes.c_int),
    ]


# ---------------------------------------------------------------------------
# DRM probe result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConnectorInfo:
    connector_id:   int
    connector_type: str
    connection:     str      # "connected" / "disconnected" / "unknown"
    modes:          List[str]  # "WxH@Hz" strings
    mode_width:     int = 0   # pixel dimensions of the first (preferred) mode
    mode_height:    int = 0


@dataclass
class CardProbeResult:
    path:               str
    fd_ok:              bool
    fd_error:           Optional[str] = None
    libdrm_ok:          bool = False
    crtc_count:         int = 0
    connectors:         List[ConnectorInfo] = field(default_factory=list)
    accessible_crtcs:   int = 0
    probe_error:        Optional[str] = None


def _probe_card(path: str) -> CardProbeResult:
    """Open path, call drmModeGetResources, enumerate connectors and modes."""
    result = CardProbeResult(path=path, fd_ok=False)

    # 1. Open the card node
    try:
        fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    except OSError as e:
        result.fd_ok = False
        result.fd_error = f"{e.strerror} (errno {e.errno})"
        return result

    result.fd_ok = True

    try:
        if _libdrm is None:
            result.probe_error = "libdrm not loadable"
            return result

        # 2. Set up libdrm function signatures (done lazily per call to avoid
        #    global side-effects at import time in case libdrm is absent).
        drm_get_res = _libdrm.drmModeGetResources
        drm_get_res.argtypes = [ctypes.c_int]
        drm_get_res.restype  = ctypes.POINTER(_DrmModeRes)

        drm_free_res = _libdrm.drmModeFreeResources
        drm_free_res.argtypes = [ctypes.POINTER(_DrmModeRes)]
        drm_free_res.restype  = None

        drm_get_conn = _libdrm.drmModeGetConnector
        drm_get_conn.argtypes = [ctypes.c_int, ctypes.c_uint32]
        drm_get_conn.restype  = ctypes.POINTER(_DrmModeConnector)

        drm_free_conn = _libdrm.drmModeFreeConnector
        drm_free_conn.argtypes = [ctypes.POINTER(_DrmModeConnector)]
        drm_free_conn.restype  = None

        # 3. Get resources
        res_ptr = drm_get_res(fd)
        if not res_ptr:
            result.probe_error = "drmModeGetResources returned NULL (no KMS?)"
            return result

        result.libdrm_ok = True
        res = res_ptr.contents
        result.crtc_count = res.count_crtcs
        result.accessible_crtcs = res.count_crtcs  # all visible at this stage

        # 4. Enumerate connectors
        for i in range(res.count_connectors):
            conn_id = res.connectors[i]
            conn_ptr = drm_get_conn(fd, conn_id)
            if not conn_ptr:
                continue

            conn = conn_ptr.contents
            conn_name = _CONNECTOR_NAMES.get(conn.connector_type, f"type{conn.connector_type}")
            conn_label = f"{conn_name}-{conn.connector_type_id}"

            if conn.connection == _DRM_MODE_CONNECTED:
                conn_status = "connected"
            elif conn.connection == _DRM_MODE_DISCONNECTED:
                conn_status = "disconnected"
            else:
                conn_status = "unknown"

            modes: List[str] = []
            first_w = 0
            first_h = 0
            for m in range(conn.count_modes):
                mi = conn.modes[m]
                modes.append(f"{mi.hdisplay}x{mi.vdisplay}@{mi.vrefresh}")
                if m == 0:
                    first_w = mi.hdisplay
                    first_h = mi.vdisplay

            result.connectors.append(ConnectorInfo(
                connector_id=conn_id,
                connector_type=conn_label,
                connection=conn_status,
                modes=modes,
                mode_width=first_w,
                mode_height=first_h,
            ))

            drm_free_conn(conn_ptr)

        drm_free_res(res_ptr)

    except Exception as e:
        result.probe_error = f"probe exception: {e!r}"
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    return result


def probe_drm_devices() -> List[CardProbeResult]:
    """Discover all /dev/dri/card* nodes and probe each. Safe to call anytime."""
    candidates = sorted(glob.glob("/dev/dri/card*"))
    results: List[CardProbeResult] = []

    for path in candidates:
        try:
            st = os.stat(path)
            if not stat.S_ISCHR(st.st_mode):
                continue
        except OSError:
            continue
        results.append(_probe_card(path))

    return results


# ---------------------------------------------------------------------------
# libdrm bindings for framebuffer import (set up lazily on first use)
# ---------------------------------------------------------------------------

def _setup_fb_import_bindings(lib):
    """Return (prime_fd_to_handle, addfb2, rmfb) callables. Raises DirectScanoutError if missing."""
    try:
        prime_fn = lib.drmPrimeFDToHandle
        prime_fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        prime_fn.restype  = ctypes.c_int
    except AttributeError:
        raise DirectScanoutError("drmPrimeFDToHandle not found in libdrm")

    try:
        addfb2_fn = lib.drmModeAddFB2
        addfb2_fn.argtypes = [
            ctypes.c_int,                            # fd
            ctypes.c_uint32, ctypes.c_uint32,        # width, height
            ctypes.c_uint32,                         # pixel_format
            ctypes.c_uint32 * 4,                     # bo_handles[4]
            ctypes.c_uint32 * 4,                     # pitches[4]
            ctypes.c_uint32 * 4,                     # offsets[4]
            ctypes.POINTER(ctypes.c_uint32),         # buf_id
            ctypes.c_uint32,                         # flags
        ]
        addfb2_fn.restype = ctypes.c_int
    except AttributeError:
        raise DirectScanoutError("drmModeAddFB2 not found in libdrm")

    try:
        rmfb_fn = lib.drmModeRmFB
        rmfb_fn.argtypes = [ctypes.c_int, ctypes.c_uint32]
        rmfb_fn.restype  = ctypes.c_int
    except AttributeError:
        raise DirectScanoutError("drmModeRmFB not found in libdrm")

    return prime_fn, addfb2_fn, rmfb_fn


def _setup_modesetting_bindings(lib):
    """Return (get_encoder, free_encoder, get_crtc, free_crtc, set_crtc). Raises DirectScanoutError if missing."""
    try:
        ge = lib.drmModeGetEncoder
        ge.argtypes = [ctypes.c_int, ctypes.c_uint32]
        ge.restype  = ctypes.POINTER(_DrmModeEncoder)
    except AttributeError:
        raise DirectScanoutError("drmModeGetEncoder not found in libdrm")

    try:
        fe = lib.drmModeFreeEncoder
        fe.argtypes = [ctypes.POINTER(_DrmModeEncoder)]
        fe.restype  = None
    except AttributeError:
        raise DirectScanoutError("drmModeFreeEncoder not found in libdrm")

    try:
        gc = lib.drmModeGetCrtc
        gc.argtypes = [ctypes.c_int, ctypes.c_uint32]
        gc.restype  = ctypes.POINTER(_DrmModeCrtc)
    except AttributeError:
        raise DirectScanoutError("drmModeGetCrtc not found in libdrm")

    try:
        fc = lib.drmModeFreeCrtc
        fc.argtypes = [ctypes.POINTER(_DrmModeCrtc)]
        fc.restype  = None
    except AttributeError:
        raise DirectScanoutError("drmModeFreeCrtc not found in libdrm")

    try:
        sc = lib.drmModeSetCrtc
        sc.argtypes = [
            ctypes.c_int,                          # fd
            ctypes.c_uint32,                       # crtc_id
            ctypes.c_uint32,                       # bufferId (fb_id)
            ctypes.c_uint32, ctypes.c_uint32,      # x, y
            ctypes.POINTER(ctypes.c_uint32),       # connectors[]
            ctypes.c_int,                          # count
            ctypes.POINTER(_DrmModeModeInfo),      # mode
        ]
        sc.restype = ctypes.c_int
    except AttributeError:
        raise DirectScanoutError("drmModeSetCrtc not found in libdrm")

    return ge, fe, gc, fc, sc


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class OutputBackend(ABC):
    """Interface every output backend must implement."""

    @abstractmethod
    def present_dmabuf(self, buf) -> None:
        """Present a DmabufBufferState.  Raise DirectScanoutError on refusal."""

    @abstractmethod
    def present_shm(self, buf) -> None:
        """Present a BufferState (SHM path)."""


# ---------------------------------------------------------------------------
# GlesPreviewBackend  — wraps the existing SDL/GLES composite path
# ---------------------------------------------------------------------------

class GlesPreviewBackend(OutputBackend):
    """Wraps GlesDmabufRenderer (dmabuf) and PygameRenderer (SHM)."""

    def __init__(self):
        self._gles_renderer = None   # lazy-init: GlesDmabufRenderer
        self._shm_renderer  = None   # lazy-init: PygameRenderer

    # Called lazily from shm_preview_bridge to avoid circular import
    def set_gles_renderer(self, renderer):
        self._gles_renderer = renderer

    def set_shm_renderer(self, renderer):
        self._shm_renderer = renderer

    def present_dmabuf(self, buf) -> None:
        if self._gles_renderer is None:
            raise RuntimeError("GlesPreviewBackend: GLES renderer not set")
        self._gles_renderer.present_egl_image(buf.egl_image, buf.width, buf.height)

    def present_shm(self, buf) -> None:
        if self._shm_renderer is None:
            raise RuntimeError("GlesPreviewBackend: SHM renderer not set")
        self._shm_renderer.present_buffer(buf)


# ---------------------------------------------------------------------------
# KmsDirectBackend  — real device reconnaissance, scanout not yet wired
# ---------------------------------------------------------------------------

class KmsDirectBackend(OutputBackend):
    """
    Probes DRM/KMS devices on construction and stores the results.
    present_dmabuf() raises DirectScanoutError with a precise reason until
    real framebuffer/CRTC setup is implemented.
    """

    def __init__(self, logger=None):
        self._log = logger or print
        self.probe_results: List[CardProbeResult] = probe_drm_devices()
        self._log_probe()

        # Pick a candidate: first card with at least one connected connector
        self._candidate: Optional[CardProbeResult] = None
        self._candidate_connector_id: int = 0
        self._candidate_connector_info: Optional[ConnectorInfo] = None
        for r in self.probe_results:
            if r.fd_ok and r.libdrm_ok and any(
                c.connection == "connected" for c in r.connectors
            ):
                self._candidate = r
                for c in r.connectors:
                    if c.connection == "connected":
                        self._candidate_connector_id = c.connector_id
                        self._candidate_connector_info = c
                        break
                break

        # Persistent DRM fd — opened on first successful drmModeSetCrtc,
        # kept open so the scanned-out buffer stays valid between frames.
        self._drm_fd: int = -1
        # Previous frame's resources, cleaned up at start of next frame.
        self._prev_fb_id: int = 0
        self._prev_gem_handle: int = 0

    @property
    def kms_mode_size(self) -> Optional[tuple]:
        """Return (width, height) of the chosen connector's first/preferred mode,
        or None if no candidate connector was found."""
        c = self._candidate_connector_info
        if c is None or c.mode_width == 0 or c.mode_height == 0:
            return None
        return (c.mode_width, c.mode_height)

    def _log_probe(self):
        log = self._log
        if not self.probe_results:
            log("[kms-probe] no /dev/dri/card* nodes found")
            return

        for r in self.probe_results:
            if not r.fd_ok:
                log(f"[kms-probe] {r.path}: open failed — {r.fd_error}")
                continue
            if not r.libdrm_ok:
                log(f"[kms-probe] {r.path}: opened but {r.probe_error or 'drmModeGetResources failed'}")
                continue
            log(f"[kms-probe] {r.path}: crtcs={r.crtc_count} connectors={len(r.connectors)}")
            for c in r.connectors:
                mode_str = ", ".join(c.modes[:3]) + ("…" if len(c.modes) > 3 else "")
                log(f"[kms-probe]   {c.connector_type} {c.connection}"
                    + (f" modes=[{mode_str}]" if c.modes else " (no modes)"))
            if r.probe_error:
                log(f"[kms-probe] {r.path}: probe error — {r.probe_error}")

    def present_dmabuf(self, buf) -> None:
        """
        Attempt KMS direct scanout (drmPrimeFDToHandle + drmModeAddFB2 + drmModeSetCrtc).
        Raises DirectScanoutError on any failure so the caller's GLES fallback runs.
        """
        if not self.probe_results:
            raise DirectScanoutError("no DRM device nodes found in /dev/dri/")

        opened = [r for r in self.probe_results if r.fd_ok]
        if not opened:
            errors = "; ".join(f"{r.path}: {r.fd_error}" for r in self.probe_results)
            raise DirectScanoutError(f"could not open any DRM node ({errors})")

        kms_cards = [r for r in opened if r.libdrm_ok]
        if not kms_cards:
            reasons = "; ".join(r.probe_error or "drmModeGetResources NULL" for r in opened)
            raise DirectScanoutError(f"no KMS-capable card: {reasons}")

        if self._candidate is None or self._candidate_connector_id == 0:
            raise DirectScanoutError("no candidate card/connector selected during probe")

        self._try_commit(buf)

    def _gem_close(self, fd: int, handle: int) -> None:
        """Close a GEM handle; logs but never raises."""
        if handle == 0:
            return
        gem_close = _DrmGemClose(handle=handle, pad=0)
        try:
            fcntl.ioctl(fd, _DRM_IOCTL_GEM_CLOSE, gem_close)
        except OSError as e:
            self._log(f"[scanout] GEM handle close error: {e.strerror} (errno {e.errno})")

    def _release_prev_frame(self) -> None:
        """Free the previous frame's framebuffer and GEM handle."""
        if self._drm_fd < 0:
            return
        if _libdrm is None:
            return
        if self._prev_fb_id:
            rmfb = _libdrm.drmModeRmFB
            rmfb.argtypes = [ctypes.c_int, ctypes.c_uint32]
            rmfb.restype  = ctypes.c_int
            ret = rmfb(self._drm_fd, self._prev_fb_id)
            if ret != 0:
                self._log(f"[scanout] drmModeRmFB(prev fb={self._prev_fb_id}) failed ret={ret}")
        if self._prev_gem_handle:
            self._gem_close(self._drm_fd, self._prev_gem_handle)
        self._prev_fb_id = 0
        self._prev_gem_handle = 0

    def _try_commit(self, buf) -> None:
        """
        Import buf's dmabuf as a GEM handle, create a KMS framebuffer,
        walk connector→encoder→CRTC, call drmModeSetCrtc.
        Raises DirectScanoutError on failure (resources cleaned up before raise).
        """
        log = self._log

        if not buf.planes:
            raise DirectScanoutError("DmabufBufferState has no planes")
        plane0  = buf.planes[0]
        prime_fd = plane0["fd"]
        stride   = plane0["stride"]
        offset   = plane0["offset"]

        if _libdrm is None:
            raise DirectScanoutError("libdrm not available")

        prime_fn, addfb2_fn, rmfb_fn = _setup_fb_import_bindings(_libdrm)
        ge, fe, gc, fc, set_crtc = _setup_modesetting_bindings(_libdrm)

        # Open (or reuse) the persistent DRM fd
        if self._drm_fd < 0:
            card_path = self._candidate.path
            try:
                self._drm_fd = os.open(card_path, os.O_RDWR | os.O_CLOEXEC)
                log(f"[scanout] opened DRM fd={self._drm_fd} ({card_path})")
            except OSError as e:
                raise DirectScanoutError(
                    f"could not open {card_path}: {e.strerror} (errno {e.errno})"
                )

        fd = self._drm_fd

        # Release the buffer the display was scanning from last frame
        self._release_prev_frame()

        handle = ctypes.c_uint32(0)
        handle_valid = False
        fb_id = ctypes.c_uint32(0)

        try:
            # ------------------------------------------------------------------
            # Step 1: dmabuf fd → GEM handle
            # ------------------------------------------------------------------
            ret = prime_fn(fd, prime_fd, ctypes.byref(handle))
            if ret != 0:
                errno_val = ctypes.get_errno()
                if errno_val == 0 and ret < 0:
                    errno_val = -ret
                raise DirectScanoutError(
                    f"drmPrimeFDToHandle failed ret={ret} "
                    f"errno={errno_val} ({os.strerror(errno_val)})"
                )
            handle_valid = True
            log(f"[scanout] drmPrimeFDToHandle succeeded handle={handle.value}")

            # ------------------------------------------------------------------
            # Step 2: GEM handle → KMS framebuffer
            # ------------------------------------------------------------------
            bo_handles = (ctypes.c_uint32 * 4)(handle.value, 0, 0, 0)
            pitches    = (ctypes.c_uint32 * 4)(stride, 0, 0, 0)
            offsets    = (ctypes.c_uint32 * 4)(offset, 0, 0, 0)

            ret = addfb2_fn(
                fd, buf.width, buf.height, buf.format,
                bo_handles, pitches, offsets,
                ctypes.byref(fb_id), 0,
            )
            if ret != 0:
                errno_val = ctypes.get_errno()
                if errno_val == 0 and ret < 0:
                    errno_val = -ret
                raise DirectScanoutError(
                    f"drmModeAddFB2 failed ret={ret} "
                    f"errno={errno_val} ({os.strerror(errno_val)}) "
                    f"[{buf.width}x{buf.height} fmt=0x{buf.format:08X}]"
                )
            log(f"[scanout] drmModeAddFB2 succeeded fb_id={fb_id.value}")

            # ------------------------------------------------------------------
            # Step 3: connector → encoder → CRTC
            # ------------------------------------------------------------------
            conn_id = self._candidate_connector_id

            # Re-read the connector for its current encoder_id and preferred mode
            conn_ptr = _libdrm.drmModeGetConnector
            conn_ptr.argtypes = [ctypes.c_int, ctypes.c_uint32]
            conn_ptr.restype  = ctypes.POINTER(_DrmModeConnector)
            free_conn = _libdrm.drmModeFreeConnector
            free_conn.argtypes = [ctypes.POINTER(_DrmModeConnector)]
            free_conn.restype  = None

            c_ptr = conn_ptr(fd, conn_id)
            if not c_ptr:
                raise DirectScanoutError(f"drmModeGetConnector({conn_id}) returned NULL")

            conn = c_ptr.contents
            encoder_id = conn.encoder_id
            if conn.count_modes < 1:
                free_conn(c_ptr)
                raise DirectScanoutError(f"connector {conn_id} has no modes")

            # Use the first (preferred) mode from the connector
            mode = conn.modes[0]
            mode_desc = f"{mode.hdisplay}x{mode.vdisplay}@{mode.vrefresh}"
            free_conn(c_ptr)

            if encoder_id == 0:
                raise DirectScanoutError(
                    f"connector {conn_id} has no active encoder "
                    f"(display may not be initialised by the native compositor)"
                )

            enc_ptr = ge(fd, encoder_id)
            if not enc_ptr:
                raise DirectScanoutError(
                    f"drmModeGetEncoder({encoder_id}) returned NULL"
                )
            crtc_id = enc_ptr.contents.crtc_id
            fe(enc_ptr)

            if crtc_id == 0:
                raise DirectScanoutError(
                    f"encoder {encoder_id} has no active CRTC"
                )
            log(f"[scanout] CRTC path: connector={conn_id} encoder={encoder_id} crtc={crtc_id} mode={mode_desc}")

            # ------------------------------------------------------------------
            # Step 4: drmModeSetCrtc — actual display commit
            # ------------------------------------------------------------------
            conn_arr = (ctypes.c_uint32 * 1)(conn_id)
            mode_copy = _DrmModeModeInfo()
            ctypes.memmove(ctypes.byref(mode_copy), ctypes.byref(mode), ctypes.sizeof(_DrmModeModeInfo))

            ret = set_crtc(
                fd,
                crtc_id,
                fb_id.value,
                0, 0,                     # x, y offset in framebuffer
                conn_arr, 1,              # connectors
                ctypes.byref(mode_copy),
            )
            if ret != 0:
                errno_val = ctypes.get_errno()
                # libdrm sometimes returns -errno directly with errno==0 in libc
                if errno_val == 0 and ret < 0:
                    errno_val = -ret
                _ERRNO_NAMES = {
                    1:  "EPERM",
                    13: "EACCES",
                    16: "EBUSY",
                    22: "EINVAL",
                    28: "ENOSPC",
                }
                _ERRNO_HINTS = {
                    1:  "operation not permitted",
                    13: "not DRM master — run on a free VT or without X/Wayland",
                    16: "CRTC in use by another master",
                    22: "invalid argument — mode/fb size mismatch?",
                    28: "no space left — fb dimensions exceed CRTC limit?",
                }
                ename = _ERRNO_NAMES.get(errno_val, str(errno_val))
                hint = _ERRNO_HINTS.get(errno_val, "")
                hint_str = f" ({hint})" if hint else ""
                raise DirectScanoutError(
                    f"drmModeSetCrtc failed ret={ret} "
                    f"errno={errno_val} [{ename}]{hint_str}"
                )

            log(f"[scanout] drmModeSetCrtc succeeded — direct scanout active "
                f"crtc={crtc_id} fb={fb_id.value} {buf.width}x{buf.height}")

            # Success: hand off ownership to the next-frame cleanup cycle
            self._prev_fb_id     = fb_id.value
            self._prev_gem_handle = handle.value
            # Return normally — caller must NOT run GLES fallback

        except DirectScanoutError:
            # On any failure: clean up this frame's resources immediately
            if fb_id.value:
                rmfb_fn(fd, fb_id.value)
            if handle_valid:
                self._gem_close(fd, handle.value)
            raise

        except Exception as e:
            if fb_id.value:
                rmfb_fn(fd, fb_id.value)
            if handle_valid:
                self._gem_close(fd, handle.value)
            raise DirectScanoutError(f"unexpected error in _try_commit: {e!r}")

    def close(self) -> None:
        """Release persistent DRM resources. Call on compositor shutdown."""
        self._release_prev_frame()
        if self._drm_fd >= 0:
            try:
                os.close(self._drm_fd)
            except OSError:
                pass
            self._drm_fd = -1

    def present_shm(self, buf) -> None:
        raise DirectScanoutError("KmsDirectBackend does not support SHM buffers")
