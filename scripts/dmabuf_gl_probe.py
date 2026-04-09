#!/usr/bin/env python3
import ctypes
import time
from ctypes.util import find_library

import pygame


# ---- SDL / pygame GL constants ----
GL_CONTEXT_MAJOR_VERSION = pygame.GL_CONTEXT_MAJOR_VERSION
GL_CONTEXT_MINOR_VERSION = pygame.GL_CONTEXT_MINOR_VERSION
GL_CONTEXT_PROFILE_MASK = pygame.GL_CONTEXT_PROFILE_MASK
GL_CONTEXT_PROFILE_ES = pygame.GL_CONTEXT_PROFILE_ES
GL_DOUBLEBUFFER = pygame.GL_DOUBLEBUFFER

# ---- GL constants ----
GL_VENDOR = 0x1F00
GL_RENDERER = 0x1F01
GL_VERSION = 0x1F02
GL_EXTENSIONS = 0x1F03
GL_COLOR_BUFFER_BIT = 0x00004000
GL_TEXTURE_2D = 0x0DE1

# ---- ctypes libs ----
libegl = ctypes.CDLL(find_library("EGL"))
libgles = ctypes.CDLL(find_library("GLESv2"))

# ---- ctypes signatures ----
libegl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
libegl.eglGetProcAddress.restype = ctypes.c_void_p

libgles.glGetString.argtypes = [ctypes.c_uint]
libgles.glGetString.restype = ctypes.c_char_p

libgles.glClearColor.argtypes = [ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
libgles.glClearColor.restype = None

libgles.glClear.argtypes = [ctypes.c_uint]
libgles.glClear.restype = None

libgles.glViewport.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
libgles.glViewport.restype = None

libgles.glGenTextures.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint)]
libgles.glGenTextures.restype = None

libgles.glBindTexture.argtypes = [ctypes.c_uint, ctypes.c_uint]
libgles.glBindTexture.restype = None

libgles.glTexParameteri.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
libgles.glTexParameteri.restype = None


def gl_string(which: int) -> str:
    ptr = libgles.glGetString(which)
    if not ptr:
        return ""
    return ptr.decode("utf-8", errors="replace")


def main():
    pygame.init()
    pygame.display.gl_set_attribute(GL_CONTEXT_PROFILE_MASK, GL_CONTEXT_PROFILE_ES)
    pygame.display.gl_set_attribute(GL_CONTEXT_MAJOR_VERSION, 2)
    pygame.display.gl_set_attribute(GL_CONTEXT_MINOR_VERSION, 0)
    pygame.display.gl_set_attribute(GL_DOUBLEBUFFER, 1)

    screen = pygame.display.set_mode((640, 360), pygame.OPENGL | pygame.DOUBLEBUF)
    pygame.display.set_caption("moksha-warp dmabuf gl probe")

    print("screen:", screen, flush=True)
    print("driver:", pygame.display.get_driver(), flush=True)
    print("wm_info:", pygame.display.get_wm_info(), flush=True)

    vendor = gl_string(GL_VENDOR)
    renderer = gl_string(GL_RENDERER)
    version = gl_string(GL_VERSION)
    extensions = gl_string(GL_EXTENSIONS)

    print("GL_VENDOR:", vendor, flush=True)
    print("GL_RENDERER:", renderer, flush=True)
    print("GL_VERSION:", version, flush=True)
    print("Has GL_OES_EGL_image:", "GL_OES_EGL_image" in extensions, flush=True)
    print("Has GL_OES_EGL_image_external:", "GL_OES_EGL_image_external" in extensions, flush=True)

    proc = libegl.eglGetProcAddress(b"glEGLImageTargetTexture2DOES")
    print("eglGetProcAddress(glEGLImageTargetTexture2DOES):", hex(proc) if proc else None, flush=True)

    libgles.glViewport(0, 0, 640, 360)

    # just flash colors a few frames so we know the GL context is real
    colors = [
        (0.12, 0.12, 0.16, 1.0),
        (0.20, 0.08, 0.08, 1.0),
        (0.08, 0.16, 0.08, 1.0),
        (0.08, 0.10, 0.22, 1.0),
    ]

    start = time.time()
    i = 0
    running = True
    while running and time.time() - start < 3.0:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        c = colors[i % len(colors)]
        i += 1
        libgles.glClearColor(*c)
        libgles.glClear(GL_COLOR_BUFFER_BIT)
        pygame.display.flip()
        time.sleep(0.20)

    pygame.quit()


if __name__ == "__main__":
    main()
