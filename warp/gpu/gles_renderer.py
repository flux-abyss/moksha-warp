#!/usr/bin/env python3

import ctypes
from ctypes.util import find_library
import os

import pygame


GL_CONTEXT_MAJOR_VERSION = pygame.GL_CONTEXT_MAJOR_VERSION
GL_CONTEXT_MINOR_VERSION = pygame.GL_CONTEXT_MINOR_VERSION
GL_CONTEXT_PROFILE_MASK  = pygame.GL_CONTEXT_PROFILE_MASK
GL_CONTEXT_PROFILE_ES    = pygame.GL_CONTEXT_PROFILE_ES
GL_DOUBLEBUFFER          = pygame.GL_DOUBLEBUFFER

GL_COLOR_BUFFER_BIT = 0x00004000
GL_TEXTURE_2D       = 0x0DE1
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_TEXTURE_WRAP_S   = 0x2802
GL_TEXTURE_WRAP_T   = 0x2803
GL_LINEAR           = 0x2601
GL_CLAMP_TO_EDGE    = 0x812F
GL_TRIANGLE_STRIP   = 0x0005
GL_FLOAT            = 0x1406
GL_FALSE            = 0
GL_VERTEX_SHADER    = 0x8B31
GL_FRAGMENT_SHADER  = 0x8B30
GL_COMPILE_STATUS   = 0x8B81
GL_LINK_STATUS      = 0x8B82
GL_NO_ERROR         = 0

GL_VENDOR    = 0x1F00
GL_RENDERER  = 0x1F01
GL_VERSION   = 0x1F02
GL_EXTENSIONS = 0x1F03


VERTEX_SHADER_SOURCE = b"""
attribute vec2 a_pos;
attribute vec2 a_uv;
varying vec2 v_uv;
void main() {
    v_uv = a_uv;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_SOURCE = b"""
precision mediump float;
uniform sampler2D u_tex;
varying vec2 v_uv;
void main() {
    gl_FragColor = texture2D(u_tex, v_uv);
}
"""


class GlesDmabufRenderer:
    def __init__(self, size=(640, 360)):
        self.size = size
        self.ready = False
        self.texture = ctypes.c_uint(0)   # shared scratch texture (legacy path)
        self.program  = ctypes.c_uint(0)
        self.a_pos = -1
        self.a_uv  = -1
        self.u_tex = -1
        self.egl_display = None           # captured after SDL GL context creation
        self.vertex_data = (ctypes.c_float * 16)(
            -1.0, -1.0,  0.0, 1.0,   # bottom-left  UV (0,1)
             1.0, -1.0,  1.0, 1.0,   # bottom-right UV (1,1)
            -1.0,  1.0,  0.0, 0.0,   # top-left     UV (0,0)
             1.0,  1.0,  1.0, 0.0,   # top-right    UV (1,0)
        )

        self.libegl  = ctypes.CDLL(find_library("EGL"))
        self.libgles = ctypes.CDLL(find_library("GLESv2"))

        # --- EGL proc-address ------------------------------------------------
        self.libegl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
        self.libegl.eglGetProcAddress.restype  = ctypes.c_void_p

        self.libegl.eglGetCurrentDisplay.argtypes = []
        self.libegl.eglGetCurrentDisplay.restype  = ctypes.c_void_p

        # --- GL function signatures ------------------------------------------
        self.libgles.glGetString.argtypes = [ctypes.c_uint]
        self.libgles.glGetString.restype  = ctypes.c_char_p

        self.libgles.glViewport.argtypes  = [ctypes.c_int]*4
        self.libgles.glViewport.restype   = None

        self.libgles.glClearColor.argtypes = [ctypes.c_float]*4
        self.libgles.glClearColor.restype  = None

        self.libgles.glClear.argtypes = [ctypes.c_uint]
        self.libgles.glClear.restype  = None

        self.libgles.glGenTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        self.libgles.glGenTextures.restype  = None

        self.libgles.glDeleteTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
        self.libgles.glDeleteTextures.restype  = None

        self.libgles.glBindTexture.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.libgles.glBindTexture.restype  = None

        self.libgles.glTexParameteri.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
        self.libgles.glTexParameteri.restype  = None

        self.libgles.glCreateShader.argtypes = [ctypes.c_uint]
        self.libgles.glCreateShader.restype  = ctypes.c_uint

        self.libgles.glShaderSource.argtypes = [
            ctypes.c_uint, ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_int),
        ]
        self.libgles.glShaderSource.restype = None

        self.libgles.glCompileShader.argtypes = [ctypes.c_uint]
        self.libgles.glCompileShader.restype  = None

        self.libgles.glGetShaderiv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
        self.libgles.glGetShaderiv.restype  = None

        self.libgles.glGetShaderInfoLog.argtypes = [
            ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
        ]
        self.libgles.glGetShaderInfoLog.restype = None

        self.libgles.glCreateProgram.argtypes = []
        self.libgles.glCreateProgram.restype  = ctypes.c_uint

        self.libgles.glAttachShader.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.libgles.glAttachShader.restype  = None

        self.libgles.glLinkProgram.argtypes = [ctypes.c_uint]
        self.libgles.glLinkProgram.restype  = None

        self.libgles.glGetProgramiv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
        self.libgles.glGetProgramiv.restype  = None

        self.libgles.glGetProgramInfoLog.argtypes = [
            ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p,
        ]
        self.libgles.glGetProgramInfoLog.restype = None

        self.libgles.glUseProgram.argtypes = [ctypes.c_uint]
        self.libgles.glUseProgram.restype  = None

        self.libgles.glGetAttribLocation.argtypes = [ctypes.c_uint, ctypes.c_char_p]
        self.libgles.glGetAttribLocation.restype  = ctypes.c_int

        self.libgles.glGetUniformLocation.argtypes = [ctypes.c_uint, ctypes.c_char_p]
        self.libgles.glGetUniformLocation.restype  = ctypes.c_int

        self.libgles.glUniform1i.argtypes = [ctypes.c_int, ctypes.c_int]
        self.libgles.glUniform1i.restype  = None

        self.libgles.glVertexAttribPointer.argtypes = [
            ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
            ctypes.c_ubyte, ctypes.c_int, ctypes.c_void_p,
        ]
        self.libgles.glVertexAttribPointer.restype = None

        self.libgles.glEnableVertexAttribArray.argtypes = [ctypes.c_uint]
        self.libgles.glEnableVertexAttribArray.restype  = None

        self.libgles.glDrawArrays.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        self.libgles.glDrawArrays.restype  = None

        self.libgles.glGetError.argtypes = []
        self.libgles.glGetError.restype  = ctypes.c_uint

        self.glEGLImageTargetTexture2DOES = None


    def _gl_string(self, which):
        ptr = self.libgles.glGetString(which)
        if not ptr:
            return ""
        return ptr.decode("utf-8", errors="replace")

    def _compile_shader(self, shader_type, source):
        shader = self.libgles.glCreateShader(shader_type)
        src    = ctypes.c_char_p(source)
        length = ctypes.c_int(len(source))
        self.libgles.glShaderSource(shader, 1, ctypes.byref(src), ctypes.byref(length))
        self.libgles.glCompileShader(shader)

        status = ctypes.c_int(0)
        self.libgles.glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
        if not status.value:
            buf     = ctypes.create_string_buffer(4096)
            out_len = ctypes.c_int(0)
            self.libgles.glGetShaderInfoLog(shader, len(buf), ctypes.byref(out_len), buf)
            raise RuntimeError(
                f"shader compile failed: {buf.value.decode('utf-8', errors='replace')}"
            )
        return shader

    def _build_program(self):
        vs = self._compile_shader(GL_VERTEX_SHADER,   VERTEX_SHADER_SOURCE)
        fs = self._compile_shader(GL_FRAGMENT_SHADER, FRAGMENT_SHADER_SOURCE)

        program = self.libgles.glCreateProgram()
        self.libgles.glAttachShader(program, vs)
        self.libgles.glAttachShader(program, fs)
        self.libgles.glLinkProgram(program)

        status = ctypes.c_int(0)
        self.libgles.glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
        if not status.value:
            buf     = ctypes.create_string_buffer(4096)
            out_len = ctypes.c_int(0)
            self.libgles.glGetProgramInfoLog(program, len(buf), ctypes.byref(out_len), buf)
            raise RuntimeError(
                f"program link failed: {buf.value.decode('utf-8', errors='replace')}"
            )

        self.program = ctypes.c_uint(program)
        self.a_pos   = self.libgles.glGetAttribLocation(program, b"a_pos")
        self.a_uv    = self.libgles.glGetAttribLocation(program, b"a_uv")
        self.u_tex   = self.libgles.glGetUniformLocation(program, b"u_tex")

        if self.a_pos < 0 or self.a_uv < 0 or self.u_tex < 0:
            raise RuntimeError(
                f"program locations invalid: a_pos={self.a_pos} "
                f"a_uv={self.a_uv} u_tex={self.u_tex}"
            )

    def _make_texture(self):
        tex = ctypes.c_uint(0)
        self.libgles.glGenTextures(1, ctypes.byref(tex))
        self.libgles.glBindTexture(GL_TEXTURE_2D, tex.value)
        self.libgles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        self.libgles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        self.libgles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        self.libgles.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        return tex.value

    def _draw_fullscreen_quad(self, tex_id):
        self.libgles.glUseProgram(self.program.value)
        self.libgles.glBindTexture(GL_TEXTURE_2D, tex_id)
        self.libgles.glUniform1i(self.u_tex, 0)

        stride   = 4 * ctypes.sizeof(ctypes.c_float)
        base_ptr = ctypes.cast(self.vertex_data, ctypes.c_void_p)
        uv_ptr   = ctypes.c_void_p(base_ptr.value + 2 * ctypes.sizeof(ctypes.c_float))

        self.libgles.glEnableVertexAttribArray(self.a_pos)
        self.libgles.glVertexAttribPointer(
            self.a_pos, 2, GL_FLOAT, GL_FALSE, stride, base_ptr
        )
        self.libgles.glEnableVertexAttribArray(self.a_uv)
        self.libgles.glVertexAttribPointer(
            self.a_uv, 2, GL_FLOAT, GL_FALSE, stride, uv_ptr
        )

        self.libgles.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        err = self.libgles.glGetError()
        if err:
            print(f"[gles] glGetError after draw: 0x{err:04x}", flush=True)


    def initialize(self):
        """Create SDL window, GLES 2 context, compile shaders."""
        if not pygame.get_init():
            pygame.init()
        if not pygame.display.get_init():
            pygame.display.init()

        print("[gles] SDL_VIDEODRIVER:", os.environ.get("SDL_VIDEODRIVER"), flush=True)
        print("[gles] XDG_SESSION_TYPE:", os.environ.get("XDG_SESSION_TYPE"), flush=True)

        pygame.display.gl_set_attribute(GL_CONTEXT_PROFILE_MASK,  GL_CONTEXT_PROFILE_ES)
        pygame.display.gl_set_attribute(GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(GL_CONTEXT_MINOR_VERSION, 0)
        pygame.display.gl_set_attribute(GL_DOUBLEBUFFER, 1)

        self.screen = pygame.display.set_mode(self.size, pygame.OPENGL | pygame.DOUBLEBUF)
        pygame.display.set_caption("moksha-warp dmabuf preview")

        # Capture the EGL display that SDL just made current.
        # This must happen immediately after set_mode() while the context
        # is guaranteed to be current.
        raw_dpy = self.libegl.eglGetCurrentDisplay()
        self.egl_display = raw_dpy  # raw c_void_p value (int or None)
        print(
            f"[gles] eglGetCurrentDisplay → {raw_dpy}",
            flush=True,
        )

        vendor     = self._gl_string(GL_VENDOR)
        renderer   = self._gl_string(GL_RENDERER)
        version    = self._gl_string(GL_VERSION)
        extensions = self._gl_string(GL_EXTENSIONS)

        print("[gles] vendor:",    vendor,    flush=True)
        print("[gles] renderer:",  renderer,  flush=True)
        print("[gles] version:",   version,   flush=True)
        print("[gles] has GL_OES_EGL_image:", "GL_OES_EGL_image" in extensions, flush=True)

        proc = self.libegl.eglGetProcAddress(b"glEGLImageTargetTexture2DOES")
        if not proc:
            raise RuntimeError(
                "glEGLImageTargetTexture2DOES not available via eglGetProcAddress"
            )
        PFN = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)
        self.glEGLImageTargetTexture2DOES = PFN(proc)

        self.libgles.glViewport(0, 0, self.size[0], self.size[1])

        # Allocate the single shared texture used by present_egl_image()
        self.texture = ctypes.c_uint(self._make_texture())

        self._build_program()
        print("[gles] shader program ready", flush=True)

        self.ready = True
        return self

    def get_egl_display(self):
        if not self.ready:
            raise RuntimeError("GlesDmabufRenderer not initialized")
        return self.egl_display

    def pump_events(self):
        """Drain the SDL event queue; raise SystemExit on window-close."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise SystemExit(0)

    def present_buffer(self, surface_id, buf, egl_importer=None):
        """Present buf (DmabufBufferState) to the preview window.

        Lazy-imports the EGLImage from the dma-buf fd on first call,
        lazy-creates a per-buffer GL texture, draws, flips.
        Returns True on success. On False the buffer was never presented;
        caller must not send wl_buffer.release.
        """
        if not self.ready:
            print("[gles] present_buffer: renderer not ready", flush=True)
            return False

        # Step 1: lazy EGLImage import
        if buf.egl_image is None:
            if egl_importer is None:
                print("[gles] present_buffer: no egl_importer, cannot import", flush=True)
                return False
            try:
                plane0 = buf.planes[0]
                print(
                    f"[gles] importing dmabuf surface={surface_id}"
                    f" fd={plane0['fd']} {buf.width}x{buf.height}"
                    f" fourcc=0x{buf.format:08X} stride={plane0['stride']}"
                    f" modifier=0x{buf.modifier:016X}",
                    flush=True,
                )
                buf.egl_image = egl_importer.import_dmabuf_image(
                    fd=plane0["fd"],
                    width=buf.width,
                    height=buf.height,
                    fourcc=buf.format,
                    stride=plane0["stride"],
                    offset=plane0["offset"],
                    modifier=buf.modifier,
                )
                print(
                    f"[gles] dmabuf imported surface={surface_id}"
                    f" {buf.width}x{buf.height} egl_image={buf.egl_image}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[gles] EGLImage import failed: {exc!r}", flush=True)
                return False

        # Step 2: lazy GL texture creation
        if buf.gl_texture is None:
            try:
                tex_id = self._make_texture()     # creates + binds GL_TEXTURE_2D
                print(
                    f"[gles] calling glEGLImageTargetTexture2DOES"
                    f" tex={tex_id} image={buf.egl_image}",
                    flush=True,
                )
                self.glEGLImageTargetTexture2DOES(
                    GL_TEXTURE_2D,
                    ctypes.c_void_p(buf.egl_image),
                )
                err = self.libgles.glGetError()
                if err:
                    print(
                        f"[gles] glEGLImageTargetTexture2DOES error 0x{err:04x}"
                        f" tex={tex_id}",
                        flush=True,
                    )
                    tid = ctypes.c_uint(tex_id)
                    self.libgles.glDeleteTextures(1, ctypes.byref(tid))
                    return False
                buf.gl_texture = tex_id
                print(
                    f"[gles] texture bound tex={tex_id} surface={surface_id}"
                    f" egl_image={buf.egl_image}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[gles] texture creation failed: {exc!r}", flush=True)
                return False

        # Step 3: draw + flip
        try:
            self.libgles.glViewport(0, 0, self.size[0], self.size[1])
            self.libgles.glClearColor(0.05, 0.05, 0.08, 1.0)
            self.libgles.glClear(GL_COLOR_BUFFER_BIT)
            self._draw_fullscreen_quad(buf.gl_texture)
            pygame.display.flip()
            print(
                f"[gles] frame presented (dmabuf path)"
                f" surface={surface_id} tex={buf.gl_texture}",
                flush=True,
            )
            return True
        except Exception as exc:
            print(f"[gles] draw/flip failed: {exc!r}", flush=True)
            return False

    def present_egl_image(self, egl_image, width, height):
        """Low-level path: bind egl_image to the shared texture and draw.

        Used by GlesPreviewBackend. present_buffer() is preferred for direct
        compositor use since it handles per-buffer texture lifetimes.
        """
        if not self.ready:
            raise RuntimeError("renderer not initialized")

        print(f"[gles] present_egl_image {width}x{height} image={egl_image}", flush=True)

        self.libgles.glViewport(0, 0, self.size[0], self.size[1])
        self.libgles.glClearColor(0.08, 0.08, 0.10, 1.0)
        self.libgles.glClear(GL_COLOR_BUFFER_BIT)

        self.libgles.glUseProgram(self.program.value)
        self.libgles.glBindTexture(GL_TEXTURE_2D, self.texture.value)
        print("[gles] before glEGLImageTargetTexture2DOES", flush=True)
        self.glEGLImageTargetTexture2DOES(GL_TEXTURE_2D, ctypes.c_void_p(egl_image))
        print("[gles] after glEGLImageTargetTexture2DOES", flush=True)
        self.libgles.glUniform1i(self.u_tex, 0)

        stride   = 4 * ctypes.sizeof(ctypes.c_float)
        base_ptr = ctypes.cast(self.vertex_data, ctypes.c_void_p)

        self.libgles.glEnableVertexAttribArray(self.a_pos)
        self.libgles.glVertexAttribPointer(
            self.a_pos, 2, GL_FLOAT, GL_FALSE, stride, base_ptr
        )
        uv_ptr = ctypes.c_void_p(base_ptr.value + 2 * ctypes.sizeof(ctypes.c_float))
        self.libgles.glEnableVertexAttribArray(self.a_uv)
        self.libgles.glVertexAttribPointer(
            self.a_uv, 2, GL_FLOAT, GL_FALSE, stride, uv_ptr
        )

        print("[gles] before glDrawArrays", flush=True)
        self.libgles.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        print("[gles] after glDrawArrays", flush=True)
        err = self.libgles.glGetError()
        print(f"[gles] after draw glGetError=0x{err:04x}", flush=True)

        pygame.display.flip()
        print("[gles] flip done", flush=True)
