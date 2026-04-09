# Moksha-Warp Milestone 14
## DMA-BUF Buffer Acceptance And Release Loop

Date: 2026-03-14

---

# Summary

The moksha-warp prototype now accepts real linux-dmabuf client buffers, imports them successfully through EGL, delivers the dma-buf buffer creation event back to the client, and participates in an active attach/release loop.

This is the first point where moksha-warp is no longer merely probing dma-buf feasibility. It is now acting as a functioning dma-buf-aware compositor bridge.

---

# Test Client

Client used:

weston-simple-dmabuf-egl

Environment:

Bodhi Linux 7  
Moksha desktop (X11)  
Intel graphics / EGL 1.5  
Python bridge via moksha-warp

---

# Confirmed Working Pieces

## 1. linux-dmabuf negotiation

moksha-warp exposes:

- wl_compositor
- wl_shm
- xdg_wm_base
- zwp_linux_dmabuf_v1

The client binds zwp_linux_dmabuf_v1 successfully.

The bridge advertises linear modifiers for:

- XRGB8888
- ARGB8888

Observed log:

linux_dmabuf.modifier advertised XRGB8888/ARGB8888 linear

---

## 2. DMA-BUF parameter flow

The client successfully issues:

zwp_linux_dmabuf_v1.create_params  
zwp_linux_buffer_params_v1.add  
zwp_linux_buffer_params_v1.create  

Example observed values:

width   = 256  
height  = 256  
stride  = 1024  
format  = 875713112  
modifier = 0  

This confirms the bridge is receiving real dma-buf plane metadata from a live Wayland client.

---

## 3. EGL dma-buf import success

The bridge successfully imports the dma-buf into EGL.

Observed log:

DMABUF IMPORT SUCCESS

This confirms that:

- the dma-buf file descriptors are valid
- EGL_EXT_image_dma_buf_import works in the live compositor path
- the offered format/modifier pair is accepted by the local graphics stack

---

## 4. Compositor-side wl_buffer creation

After successful import, the bridge creates a compositor-side wl_buffer resource for the imported dma-buf.

Observed log:

created compositor dmabuf buffer resource

This is the step that converts dma-buf import viability into actual Wayland buffer acceptance.

---

## 5. created() delivery to client

The bridge now successfully sends the zwp_linux_buffer_params_v1.created event back to the client.

Observed log:

zwp_linux_buffer_params_v1.created sent

This confirms the client is no longer being forced down the immediate failed() path for dma-buf buffer creation.

---

## 6. Continuous attach / release loop

The client now repeatedly attaches the accepted dma-buf-backed wl_buffer to its surface.

The bridge repeatedly responds with wl_buffer.release.

Observed pattern:

wl_surface.attach buffer=<MyBufferResource ...>  
sending wl_buffer.release id=...  

This confirms that the compositor and client have entered a stable dma-buf buffer lifecycle loop.

That is a major milestone because it proves:

- accepted dma-buf buffers are usable by the client
- the client can reuse them
- the compositor is participating correctly in the release lifecycle

---

# What This Milestone Proves

Moksha-Warp now has working:

- dma-buf protocol negotiation
- modifier advertisement
- dma-buf plane receipt
- EGL dma-buf import
- compositor-side wl_buffer creation
- created event delivery
- attach / release lifecycle loop

This is enough to say that a real Bodhi-hosted Wayland bridge can accept and manage GPU-native client buffers.

---

# Current Limitation

The imported EGLImage is not yet visibly rendered in the preview window.

At this milestone, the compositor:

- accepts the dma-buf buffer
- tracks it
- releases it correctly

But it does not yet:

- bind the imported EGLImage to a GL texture
- draw that texture into the preview window
- present the actual imported client image visually

So the protocol and lifecycle path are working, but the preview renderer still needs final GPU presentation wiring.

---

# Why This Matters

This milestone moves moksha-warp beyond protocol experiments.

The project now demonstrates that Bodhi / Moksha can support the core architecture needed for modern Wayland compositor behavior:

client GPU buffer  
→ compositor dma-buf import  
→ compositor buffer acceptance  
→ client reuse via wl_buffer.release  

This is the essential foundation for a zero-copy or near-zero-copy compositor path.

---

# Remaining Work

The next milestone should focus on first visible dma-buf presentation.

Required steps:

1. Bind the imported EGLImage to a GL texture
2. Draw a textured quad in the preview window
3. Present the rendered frame
4. Move wl_buffer.release to occur after presentation rather than immediately after attach handling

---

# Significance

Milestone 13 proved:

"this machine can import dma-bufs into EGL"

Milestone 14 proves:

"moksha-warp can accept dma-buf buffers and participate in a live compositor buffer lifecycle"

The remaining work is renderer presentation, not protocol viability.
