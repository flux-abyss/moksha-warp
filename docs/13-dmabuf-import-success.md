# Moksha-Warp Milestone 13
## DMA-BUF Import Success

Date: 2026-03-13

---

# Summary

The moksha-warp prototype has successfully imported real dma-buf-backed client buffers into EGL.

This milestone confirms that the zero-copy path is viable on the current Bodhi / Moksha development system.

A real client now:

- binds zwp_linux_dmabuf_v1
- creates zwp_linux_buffer_params_v1 objects
- submits dma-buf plane metadata
- requests buffer creation through the dma-buf path

moksha-warp now successfully imports those dma-buf buffers with eglCreateImageKHR.

---

# Test Client

Client used:

weston-simple-dmabuf-egl

Environment:

Bodhi Linux 7  
Moksha desktop (X11)  
Python bridge running through moksha-warp

---

# Confirmed Protocol Flow

The following dma-buf client sequence was observed:

zwp_linux_dmabuf_v1.create_params  
zwp_linux_buffer_params_v1.add  
zwp_linux_buffer_params_v1.create  

Example observed parameters:

width  = 256  
height = 256  
format = 875713112  
stride = 1024  
modifier = 0  

The bridge received these values and attempted EGL import.

---

# Confirmed EGL Import Success

moksha-warp successfully imported the offered dma-buf planes through EGL.

Observed log output:

DMABUF IMPORT SUCCESS  
DMABUF IMPORT CLEANUP OK  

This confirms that:

- the offered dma-buf fd is valid
- EGL_EXT_image_dma_buf_import works in the live bridge path
- the format/modifier combination is accepted by the local graphics stack
- imported EGL images can be created and destroyed successfully

This is the first confirmed zero-copy import success in moksha-warp.

---

# Meaning

This milestone proves that zero-copy presentation is feasible on the target machine.

The following requirements are now confirmed in practice:

- linux-dmabuf Wayland protocol path works
- real clients will attempt dma-buf buffer creation
- the local EGL stack can import client dma-buf buffers
- imported dma-buf images are valid enough to be created and cleaned up successfully

This removes the final uncertainty around platform capability.

---

# Current Limitation

Although dma-buf import now succeeds, the bridge still intentionally responds with:

zwp_linux_buffer_params_v1.failed

This means the client is still told that buffer creation failed, even though import worked internally.

The bridge currently proves import viability, but does not yet:

- create a real accepted wl_buffer from the imported image
- attach imported image state to compositor surfaces
- present the imported image through a renderer path

---

# Architecture State At This Milestone

## Proven
- wl_compositor path
- wl_shm rendering path
- visible shm-backed frame rendering
- wl_buffer.release-driven buffer reuse
- linux-dmabuf negotiation
- dma-buf buffer param submission from a real client
- EGL dma-buf image import success

## Remaining
- accept dma-buf-backed buffers instead of failing them
- associate imported EGL images with wl_buffer objects
- render/present imported GPU buffers without shm fallback

---

# Significance For Bodhi / Moksha

This milestone demonstrates that a lightweight Moksha-based bridge can reach the same class of GPU-native buffer flow used by modern Wayland compositors.

If completed fully, the dma-buf path enables:

client GPU buffer  
→ compositor import  
→ presentation  

without CPU shm copies in the compositor path.

That can provide:

- lower CPU usage
- lower memory bandwidth usage
- lower latency
- higher frame rate ceilings
- better performance on integrated graphics
- modern GPU-native presentation inside a lightweight desktop stack

---

# Next Development Step

Milestone 14 should target:

accepting imported dma-buf buffers as real compositor-side buffers instead of returning failed().

That milestone will convert zero-copy import success into actual zero-copy buffer acceptance.

---

# Significance

This milestone changes the project status from:

"zero-copy might be possible"

to:

"zero-copy import is working on this machine"

The remaining work is now compositor integration, not capability discovery.
