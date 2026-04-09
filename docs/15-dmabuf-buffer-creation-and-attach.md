# Moksha-Warp Milestone 15
## DMA-BUF Buffer Creation and Surface Attach

Date: 2026-03-14

---

# Summary

moksha-warp successfully negotiates the linux-dmabuf protocol with real Wayland
clients and imports GPU-backed buffers via EGL.

A Wayland client (`weston-simple-dmabuf-egl`) can now:

1. Create linux-dmabuf buffer params
2. Send plane metadata to the compositor
3. Receive compositor-created wl_buffer resources
4. Attach those buffers to wl_surface
5. Commit the surface

This proves that moksha-warp can act as a dma-buf-aware compositor bridge
on Bodhi Linux / Moksha.

---

# Test Environment

System:

Bodhi Linux 7  
Moksha Desktop (X11)  
Intel UHD 630 GPU  
Mesa 23.2.x  
Python 3.10  
SDL2 / pygame 2.6

Wayland test client:

weston-simple-dmabuf-egl

---

# Protocol Flow Verified

Client → Server:

zwp_linux_dmabuf_v1.create_params  
zwp_linux_buffer_params_v1.add  
zwp_linux_buffer_params_v1.create  

Example parameters:

width: 256  
height: 256  
stride: 1024  
format: 875713112 (XRGB8888)  
modifier: 0

---

# Server Behavior

moksha-warp:

1. Receives dma-buf plane metadata
2. Imports the buffer via EGL_EXT_image_dma_buf_import
3. Creates a compositor-side wl_buffer resource
4. Sends zwp_linux_buffer_params_v1.created

Example log:

zwp_linux_buffer_params_v1.created sent params_id=9 buffer_id=4278190080

---

# Client Behavior

Client receives wl_buffer objects and attaches them to its surface:

zwp_linux_buffer_params_v1@9.created(new id wl_buffer@4278190080)

wl_surface@3.attach(wl_buffer@4278190080, 0, 0)
wl_surface@3.commit()

Multiple buffers are created and attached.

---

# Current Limitation

The compositor currently does not release buffers in the latest commit path.

The client eventually reports:

All buffers busy at redraw(). Server bug?

This indicates that wl_buffer.release must be sent after presentation
to allow the client to reuse buffers.

---

# Renderer Work

A GLES renderer module has been introduced:

warp/gles_dmabuf_renderer.py

This module:

- opens a pygame OPENGL window
- loads glEGLImageTargetTexture2DOES via eglGetProcAddress
- binds EGLImage objects to GL textures

Environment verification:

GL_VENDOR: Intel  
GL_RENDERER: Mesa Intel UHD 630  
GL_VERSION: OpenGL ES 3.2 Mesa  
GL_OES_EGL_image: available

Next step is drawing a textured quad using a GLES shader.

---

# Significance

This milestone proves that:

moksha-warp can negotiate dma-buf buffers and accept GPU-backed client
surfaces using the standard Wayland linux-dmabuf protocol.

This moves the project beyond protocol experiments and into a working
Wayland compositor bridge architecture.

---

# Next Milestones

1. Restore wl_buffer.release in commit path
2. Activate GLES renderer on dmabuf commits
3. Draw EGLImage using shader + fullscreen quad
4. Present real client pixels in preview window
