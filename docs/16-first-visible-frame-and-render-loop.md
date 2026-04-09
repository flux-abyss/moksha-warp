# Moksha-Warp Milestone 16
## First Visible Frame and Stable Render Loop

Date: 2026-03-14

---

# Summary

moksha-warp successfully renders real client pixels to screen using the dma-buf
path, completing the full pipeline from client buffer creation to visible output.

A Wayland client (`weston-simple-dmabuf-egl`) now:

1. Sends dma-buf-backed buffers
2. Has those buffers imported via EGL
3. Sees them rendered as GL textures
4. Receives proper wl_buffer.release signals
5. Continues rendering in a stable loop

This marks the transition from protocol-level validation to a functioning
render pipeline.

---

# Pipeline Verified

End-to-end path:

Client → dma-buf → EGLImage → GL texture → draw → display → release → repeat

Specifically:

1. Client creates dma-buf buffers via linux-dmabuf protocol
2. Compositor imports buffers using EGL_EXT_image_dma_buf_import
3. EGLImage is bound to a GL texture
4. A fullscreen quad is drawn using GLES
5. Frame is presented via SDL window
6. wl_buffer.release is sent
7. wl_callback done is sent
8. Client submits next frame

---

# Renderer Behavior

The GLES renderer (`warp/gpu/gles_renderer.py`) now:

- Initializes EGL + GLES context via SDL
- Loads `glEGLImageTargetTexture2DOES`
- Binds imported EGLImages to GL textures
- Executes draw calls:

Example:

glEGLImageTargetTexture2DOES  
glDrawArrays  
glGetError = 0x0000  
flip done  

Frames render continuously without GL errors.

---

# Buffer Lifecycle (Fixed)

Previous milestone limitation:

> buffers were not released, causing client stall

Now resolved:

- wl_buffer.release is sent after presentation
- Clients reuse buffers correctly
- No "all buffers busy" condition

This enables continuous rendering.

---

# Render Loop Stability

The compositor now maintains a stable loop:

- attach → commit  
- import → bind → draw → flip  
- release → frame callback  
- repeat  

Observed behavior:

- No crashes
- No GL errors
- Continuous frame production
- Correct synchronization between client and compositor

---

# KMS Integration (Initial)

KMS probing is active during rendering:

- `/dev/dri/card0` opened
- Connectors and modes detected
- Buffers classified per frame:

PRIMARY_SCANOUT_ELIGIBLE  
PLANE_CANDIDATE  
BLOCKED  

Current behavior:

All paths fall back to GLES preview.

Direct scanout is not yet enabled.

---

# Significance

This milestone proves that:

moksha-warp can fully process and render dma-buf-backed client buffers in real time.

This is the first point where:

- real client pixels are visible
- the compositor loop is stable
- buffer lifecycle is correct
- GPU path is functioning end-to-end

The project has moved from experimental protocol handling to a working rendering system.

---

# Next Milestones

1. Wire direct scanout path (drmModeSetCrtc / pageflip)
2. Support overlay plane assignment for PLANE_CANDIDATE buffers
3. Add multi-plane dma-buf support (NV12, YUV)
4. Improve wl_output accuracy and multi-output support