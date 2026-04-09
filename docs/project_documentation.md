# Moksha-Warp Documentation

## 1. Architecture Overview

Moksha-Warp is an experimental nested Wayland bridge for the Moksha desktop environment. The primary goal is to host Wayland-native clients inside a standard Moksha (X11) desktop window using a minimal asynchronous proxy.

The core architecture treats Python as the control plane for protocol orchestration, while the graphics stack handles buffer import and rendering. The compositor hosts a private Wayland socket inside the X11 session, negotiating Wayland and XDG shell protocols with clients, and delegating actual graphics presentation to specialized backend renderers.

## 2. Graphics Pipeline

Moksha-Warp implements two rendering pathways to support both legacy and modern GPU-native Wayland clients:

*   **Shared Memory (SHM) Pipeline**:
    *   Implements the `wl_shm` interface, advertising `XRGB8888` and `ARGB8888` formats.
    *   Reads pixel memory directly from shared memory pools and renders frames via a software or OpenGL fallback preview window.
*   **DMA-BUF (Zero-Copy) Pipeline**:
    *   Implements the `zwp_linux_dmabuf_v1` protocol.
    *   Accepts hardware-backed buffer metadata (planes, strides, modifiers) directly from the client.
    *   Imports buffers using the `EGL_EXT_image_dma_buf_import` extension, avoiding CPU-side memory copies in the compositor path.
    *   Decouples dmabuf ingestion from EGL importer availability, allowing direct DRM/KMS scanout to bypass EGL entirely when operating outside an X11 session.

## 3. Prototype Implementation

The current prototype is built on Python and PyWayland, running on Bodhi Linux.

*   **Protocol Handling**: Python handles control-plane events, including global discovery (`wl_registry`), surface creation (`wl_compositor`), XDG shell negotiation (`xdg_wm_base`, `xdg_toplevel`), and buffer lifecycles (`wl_buffer`).
*   **Renderer Backend**: A GLES renderer module (`warp/gpu/gles_renderer.py`) serves as the active preview presentation layer. It manages an OpenGL context via SDL/EGL, loads `glEGLImageTargetTexture2DOES` via `eglGetProcAddress`, binds imported `EGLImage` objects to GL textures, and draws a full-surface textured quad before swapping the SDL window.
*   **Buffer Lifecycle**: The compositor accurately participates in the `wl_surface.attach`, `wl_surface.commit`, and `wl_buffer.release` loop, validating that client GPU buffers can be tracked, used, and correctly recycled.

## 4. Hardware Capability Detection

The bridge models hardware presentation dynamically using real KMS mode discovery:

*   **KMS Integration**: The compositor queries real DRM/KMS connector and CRTC information to discover authentic display mode sizes (e.g., 1920x1080) rather than relying on assumed or hardcoded output dimensions.
*   **Scanout Classification**: Incoming dmabuf buffers are rigorously classified:
    *   `PRIMARY_SCANOUT_ELIGIBLE`: Fullscreen buffers matching the exact display mode dimensions.
    *   `PLANE_CANDIDATE`: Smaller buffers suitable for hardware overlay planes.
    *   `BLOCKED`: Intersecting formats, mismatched modifiers, or unsupported transformations.
*   **EGL Capabilities**: Validates `EGL_EXT_image_dma_buf_import`, `EGL_EXT_image_dma_buf_import_modifiers`, `EGL_KHR_image`, and `EGL_MESA_image_dma_buf_export` to verify zero-copy capabilities from the userspace graphics stack.

## 5. Current Status

The dma-buf preview pipeline is validated end-to-end and confirmed working with real
Wayland clients (`weston-simple-dmabuf-egl`, `weston-simple-shm`).

*   **Protocol**: `wl_compositor`, `wl_shm`, `xdg_wm_base`, and `zwp_linux_dmabuf_v1` are active and stable.
*   **Presentation Loop**: dma-buf frames are imported as `EGLImage`, bound to GL textures, drawn as textured quads, and presented in the preview window. This runs continuously at the client's frame rate.
*   **Lifecycle**: `wl_surface.attach` → `wl_surface.commit` → draw → `wl_buffer.release` → frame callback delivery operates correctly. Resources (GL textures, EGLImages, plane fds) are cleaned up on buffer destroy. Shutdown is clean.
*   **Decoupling**: DMA-BUF buffer ingestion runs independently of EGL context availability.
*   **Scanout Classification**: Incoming dma-buf surfaces are classified as `PRIMARY_SCANOUT_ELIGIBLE`, `PLANE_CANDIDATE`, or `BLOCKED` based on real KMS mode discovery. The classification is correct; the KMS pageflip itself is not yet implemented.
*   **Virtual Terminal**: DMA-BUF buffers can be accepted on a free VT without an X11 host (EGL preview unavailable there, but ingestion works).

The compositor is not production-grade. It is a prototype that proves the zero-copy
pipeline is achievable on this hardware stack. Direct scanout (KMS pageflip) and
hardware overlay planes are the next technical milestones.

## 6. Near-Term Technical Priorities

*   **Direct Scanout**: Wire the existing `PRIMARY_SCANOUT_ELIGIBLE` classification to an actual `drmModeSetCrtc` / `drmModePageFlip` call on a free VT. The KMS plumbing is in place; the pageflip is not yet connected.
*   **Hardware Overlay Planes**: Implement hardware overlay-plane presentation for `PLANE_CANDIDATE` surfaces (smaller-than-mode dma-buf surfaces), reducing GPU compositing overhead.
*   **Multi-Plane Formats**: Extend `zwp_linux_buffer_params_v1` to accept NV12 and YUV planar formats so clients using those formats are not immediately rejected.
*   **Input Skeleton**: Add minimal `wl_keyboard` / `wl_pointer` stubs so clients that call `wl_seat.get_keyboard()` or `wl_seat.get_pointer()` do not encounter unhandled protocol paths.
*   **Repeated Real-Client Validation**: Run `weston-terminal`, `mpv --gpu-context=wayland`, and GTK4 clients against the compositor to expose unimplemented protocol paths.
*   **Moksha Integration**: Transition the standalone preview interface to map Wayland surfaces directly into Moksha-managed window constructs.
