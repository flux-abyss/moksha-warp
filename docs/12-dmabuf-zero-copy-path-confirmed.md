# Moksha-Warp Milestone 12
## DMA-BUF Zero-Copy Path Confirmed

Date: 2026-03-13

---

# Summary

The moksha-warp prototype has reached the final pre-import milestone for zero-copy rendering.

This milestone confirms that:

- the system Wayland bindings expose the linux-dmabuf protocol
- a real client can bind zwp_linux_dmabuf_v1
- a real client can submit dma-buf-backed buffer parameters
- the local EGL stack supports dma-buf image import extensions

This means zero-copy rendering is no longer theoretical for moksha-warp.  
The remaining work is implementing actual dma-buf buffer import and presentation.

---

# Key Result

A real dma-buf client path was observed.

Client used:

weston-simple-dmabuf-egl

Observed protocol sequence:

zwp_linux_dmabuf_v1.create_params  
zwp_linux_buffer_params_v1.add  
zwp_linux_buffer_params_v1.create  

Current server behavior intentionally returns:

zwp_linux_buffer_params_v1.failed

This confirms the client is successfully attempting a dma-buf rendering path and the bridge is now receiving real dma-buf buffer metadata.

---

# Why This Matters

Before this milestone, moksha-warp had already proven:

- Wayland protocol handshake
- XDG shell negotiation
- wl_shm pool and buffer handling
- visible frame rendering through shared memory
- working frame loop and buffer reuse

This milestone moves the project beyond shm-only rendering and proves that the zero-copy route is visible and reachable.

The project is now at the point where actual dma-buf import can be attempted.

---

# Confirmed DMA-BUF Protocol Support

The installed pywayland bindings expose:

- ZwpLinuxDmabufV1
- ZwpLinuxBufferParamsV1
- ZwpLinuxDmabufFeedbackV1

Observed request support includes:

## zwp_linux_dmabuf_v1
- destroy
- create_params
- get_default_feedback
- get_surface_feedback

## zwp_linux_buffer_params_v1
- destroy
- add
- create
- create_immed

This confirms moksha-warp has the protocol objects needed for a real dma-buf-backed buffer path.

---

# Confirmed Client Behavior

The following client behavior was observed with weston-simple-dmabuf-egl:

1. Bind zwp_linux_dmabuf_v1
2. Receive advertised modifiers
3. Create zwp_linux_buffer_params_v1 objects
4. Add dma-buf plane metadata
5. Attempt buffer creation through dma-buf path

Example observed values:

format = 875713112  
width  = 256  
height = 256  
stride = 1024  
modifier_hi = 0  
modifier_lo = 0  

This is the first confirmed evidence that a real client is offering dma-buf-backed buffers to moksha-warp.

---

# Confirmed EGL Capability

The local graphics stack reports support for:

- EGL_EXT_image_dma_buf_import
- EGL_EXT_image_dma_buf_import_modifiers
- EGL_KHR_image
- EGL_MESA_image_dma_buf_export

These extensions confirm that the machine is capable of creating EGL images from dma-buf-backed memory.

This is the key platform requirement for zero-copy compositor import.

---

# Current Architecture State

At this milestone, moksha-warp now has:

## Proven
- wl_compositor path
- wl_shm rendering path
- visible frame rendering
- buffer reuse through wl_buffer.release
- dmabuf protocol availability
- dmabuf client negotiation
- EGL dma-buf import capability in userspace stack

## Not Yet Implemented
- actual dma-buf EGL image import in compositor path
- wl_buffer creation from imported dma-buf-backed image
- GPU-native presentation of imported dma-buf buffers

---

# Meaning For Bodhi / Moksha

If the remaining dma-buf import step is completed successfully, Moksha-Warp gains the foundation for true zero-copy Wayland presentation.

That would allow:

client GPU buffer  
→ compositor import  
→ presentation  

without CPU shm copy in the compositor path.

Expected benefits include:

- lower CPU usage
- lower memory bandwidth pressure
- lower latency
- higher frame rate ceilings
- better performance on integrated graphics systems
- more modern compositor behavior while keeping Moksha’s lightweight design goals

This is especially significant for Bodhi because it creates a path toward a lightweight desktop environment with modern GPU-native Wayland presentation.

---

# Current Limitation

Although clients now attempt dma-buf buffer creation, the server currently returns failure intentionally.

This is expected at this stage.

The remaining missing piece is:

- import dma-buf file descriptors into EGL images
- associate imported image data with wl_buffer objects
- present those buffers without falling back to shm

---

# Next Development Step

Milestone 13 should target:

actual dma-buf import using eglCreateImageKHR and first successful zero-copy buffer acceptance.

That milestone will represent the first true strike against the Zero Copy Dragon.

---

# Significance

This milestone proves that zero-copy rendering is not blocked by missing protocol bindings or missing EGL support.

The path is now open.

The remaining challenge is implementation, not feasibility.
