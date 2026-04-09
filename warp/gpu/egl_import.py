#!/usr/bin/env python3
import ctypes
import ctypes.util
import os

# --- EGL constants ---
EGL_DEFAULT_DISPLAY = ctypes.c_void_p(0)
EGL_NO_CONTEXT = ctypes.c_void_p(0)
EGL_NO_IMAGE_KHR = ctypes.c_void_p(0)

EGL_NONE = 0x3038
EGL_WIDTH = 0x3057
EGL_HEIGHT = 0x3056

EGL_LINUX_DMA_BUF_EXT = 0x3270
EGL_LINUX_DRM_FOURCC_EXT = 0x3271
EGL_DMA_BUF_PLANE0_FD_EXT = 0x3272
EGL_DMA_BUF_PLANE0_OFFSET_EXT = 0x3273
EGL_DMA_BUF_PLANE0_PITCH_EXT = 0x3274
EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT = 0x3443
EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT = 0x3444

EGL_EXTENSIONS = 0x3055

# DRM fourcc
DRM_FORMAT_XRGB8888 = 0x34325258
DRM_FORMAT_ARGB8888 = 0x34325241

# Sentinel modifier values that must NOT be passed to eglCreateImageKHR
# DRM_FORMAT_MOD_INVALID = fourcc_mod_code(0, ((1ULL<<56)-1)) = 0x00ffffffffffffff
# Some clients also send UINT64_MAX when "no modifier" is intended.
DRM_FORMAT_MOD_INVALID = 0x00ffffffffffffff
_MOD_UINT64_MAX        = 0xffffffffffffffff


class EglDmabufError(RuntimeError):
    pass


def _load_library(name_hint: str):
    path = ctypes.util.find_library(name_hint)
    if not path:
        raise EglDmabufError(f"Could not find library: {name_hint}")
    return ctypes.CDLL(path)


_libEGL = _load_library("EGL")

# Core EGL symbols
_eglGetDisplay = _libEGL.eglGetDisplay
_eglGetDisplay.argtypes = [ctypes.c_void_p]
_eglGetDisplay.restype = ctypes.c_void_p

_eglInitialize = _libEGL.eglInitialize
_eglInitialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
_eglInitialize.restype = ctypes.c_uint

_eglTerminate = _libEGL.eglTerminate
_eglTerminate.argtypes = [ctypes.c_void_p]
_eglTerminate.restype = ctypes.c_uint

_eglQueryString = _libEGL.eglQueryString
_eglQueryString.argtypes = [ctypes.c_void_p, ctypes.c_int]
_eglQueryString.restype = ctypes.c_char_p

_eglGetError = _libEGL.eglGetError
_eglGetError.argtypes = []
_eglGetError.restype = ctypes.c_uint

_eglGetProcAddress = _libEGL.eglGetProcAddress
_eglGetProcAddress.argtypes = [ctypes.c_char_p]
_eglGetProcAddress.restype = ctypes.c_void_p


def _egl_bool(ok: int, what: str):
    if not ok:
        raise EglDmabufError(f"{what} failed, eglGetError=0x{_eglGetError():04x}")


def _require_proc(name: str, restype, argtypes):
    ptr = _eglGetProcAddress(name.encode("ascii"))
    if not ptr:
        raise EglDmabufError(f"eglGetProcAddress could not resolve {name}")
    fn_type = ctypes.CFUNCTYPE(restype, *argtypes)
    return fn_type(ptr)


_eglCreateImageKHR = _require_proc(
    "eglCreateImageKHR",
    ctypes.c_void_p,
    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)],
)

_eglDestroyImageKHR = _require_proc(
    "eglDestroyImageKHR",
    ctypes.c_uint,
    [ctypes.c_void_p, ctypes.c_void_p],
)


class EglDmabufImporter:
    def __init__(self):
        self.display = None
        self.major = 0
        self.minor = 0
        self.extensions = ""

    def initialize(self):
        """Initialize by calling eglGetDisplay(EGL_DEFAULT_DISPLAY).

        NOTE: Only use this when no GL context exists yet.  When a GLES
        renderer has already created its own EGL context, use
        initialize_with_display() instead so both objects share the same
        EGL display handle (required by eglCreateImageKHR).
        """
        dpy = _eglGetDisplay(EGL_DEFAULT_DISPLAY)
        if not dpy:
            raise EglDmabufError("eglGetDisplay returned NULL")

        major = ctypes.c_int()
        minor = ctypes.c_int()
        _egl_bool(_eglInitialize(dpy, ctypes.byref(major), ctypes.byref(minor)), "eglInitialize")

        exts = _eglQueryString(dpy, EGL_EXTENSIONS)
        ext_str = exts.decode("utf-8", errors="replace") if exts else ""

        self.display = dpy
        self.major = major.value
        self.minor = minor.value
        self.extensions = ext_str
        print(f"[egl-importer] display={int(ctypes.cast(dpy, ctypes.c_void_p).value or 0)}", flush=True)
        return self

    def initialize_with_display(self, display_ptr):
        """Initialize using an EGL display that is already current.

        Call this after a GLES renderer has created its context so that
        eglCreateImageKHR uses the same display handle as the active GL
        context.  *display_ptr* must be a non-NULL ctypes void-pointer or
        integer value returned by eglGetCurrentDisplay().
        """
        if not display_ptr:
            raise EglDmabufError("initialize_with_display: display_ptr is NULL")

        # Accept both ctypes c_void_p and raw integers
        if isinstance(display_ptr, int):
            dpy = display_ptr
        else:
            dpy = ctypes.cast(display_ptr, ctypes.c_void_p).value or 0
            if not dpy:
                raise EglDmabufError("initialize_with_display: cast yielded NULL")

        major = ctypes.c_int()
        minor = ctypes.c_int()
        _egl_bool(
            _eglInitialize(dpy, ctypes.byref(major), ctypes.byref(minor)),
            "eglInitialize(with_display)",
        )

        exts = _eglQueryString(dpy, EGL_EXTENSIONS)
        ext_str = exts.decode("utf-8", errors="replace") if exts else ""

        self.display = dpy
        self.major = major.value
        self.minor = minor.value
        self.extensions = ext_str
        print(
            f"[egl-importer] shared display={dpy} "
            f"EGL {self.major}.{self.minor}",
            flush=True,
        )
        return self

    def terminate(self):
        if self.display:
            _eglTerminate(self.display)
            self.display = None

    def has_extension(self, name: str) -> bool:
        return name in self.extensions.split()

    def import_dmabuf_image(
        self,
        fd: int,
        width: int,
        height: int,
        fourcc: int,
        stride: int,
        offset: int = 0,
        modifier: int = 0,
    ):
        """Import a dma-buf fd as an EGLImage.

        Modifier attributes are included only when:
          * modifier is a real modifier (not INVALID / UINT64_MAX)
          * the EGL_EXT_image_dma_buf_import_modifiers extension is present
        Omitting them for sentinel values avoids eglCreateImageKHR failures
        with clients (e.g. weston-simple-dmabuf-egl) that pass INVALID.
        """
        if self.display is None:
            raise EglDmabufError("EGL display not initialized")

        # Determine whether to include modifier attributes.
        # A modifier of 0 (DRM_FORMAT_MOD_LINEAR) is valid and should be
        # included when the extension is present so the driver can confirm
        # the tiling layout is linear.
        _invalid_mod = modifier in (DRM_FORMAT_MOD_INVALID, _MOD_UINT64_MAX)
        _has_mod_ext = self.has_extension("EGL_EXT_image_dma_buf_import_modifiers")
        include_modifier = (not _invalid_mod) and _has_mod_ext

        print(
            f"[egl-importer] import_dmabuf_image"
            f" {width}x{height} fourcc=0x{fourcc:08X}"
            f" stride={stride} offset={offset}"
            f" modifier=0x{modifier:016X}"
            f" include_mod={include_modifier}"
            f" has_mod_ext={_has_mod_ext}",
            flush=True,
        )

        if include_modifier:
            mod_lo = modifier & 0xFFFFFFFF
            mod_hi = (modifier >> 32) & 0xFFFFFFFF
            attrs = (ctypes.c_int * 17)(
                EGL_WIDTH, width,
                EGL_HEIGHT, height,
                EGL_LINUX_DRM_FOURCC_EXT, fourcc,
                EGL_DMA_BUF_PLANE0_FD_EXT, fd,
                EGL_DMA_BUF_PLANE0_OFFSET_EXT, offset,
                EGL_DMA_BUF_PLANE0_PITCH_EXT, stride,
                EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT, mod_lo,
                EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT, mod_hi,
                EGL_NONE,
            )
        else:
            attrs = (ctypes.c_int * 13)(
                EGL_WIDTH, width,
                EGL_HEIGHT, height,
                EGL_LINUX_DRM_FOURCC_EXT, fourcc,
                EGL_DMA_BUF_PLANE0_FD_EXT, fd,
                EGL_DMA_BUF_PLANE0_OFFSET_EXT, offset,
                EGL_DMA_BUF_PLANE0_PITCH_EXT, stride,
                EGL_NONE,
            )

        print("[egl-importer] calling eglCreateImageKHR", flush=True)
        image = _eglCreateImageKHR(
            self.display,
            EGL_NO_CONTEXT,
            EGL_LINUX_DMA_BUF_EXT,
            None,
            attrs,
        )
        if not image or image == EGL_NO_IMAGE_KHR:
            err = _eglGetError()
            raise EglDmabufError(
                f"eglCreateImageKHR failed eglGetError=0x{err:04x}"
                f" (modifier_included={include_modifier})"
            )

        print(f"[egl-importer] egl image created image={image}", flush=True)
        return image

    def destroy_image(self, image):
        if self.display is None:
            raise EglDmabufError("EGL display not initialized")
        _egl_bool(_eglDestroyImageKHR(self.display, image), "eglDestroyImageKHR")


def quick_probe():
    imp = EglDmabufImporter().initialize()
    print(f"EGL initialized: {imp.major}.{imp.minor}")
    print("Has EGL_EXT_image_dma_buf_import:", imp.has_extension("EGL_EXT_image_dma_buf_import"))
    print("Has EGL_EXT_image_dma_buf_import_modifiers:", imp.has_extension("EGL_EXT_image_dma_buf_import_modifiers"))
    print("Has EGL_KHR_image:", imp.has_extension("EGL_KHR_image"))
    imp.terminate()


if __name__ == "__main__":
    quick_probe()
