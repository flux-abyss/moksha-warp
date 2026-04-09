# Moksha-Warp

Experimental nested Wayland bridge for Moksha.

Goal:
Host Wayland-native clients inside a standard Moksha (X11) desktop window using a minimal asynchronous proxy.

Key idea:
Python handles control-plane orchestration while the graphics stack handles buffer import and rendering.

Initial milestone:
- Start private Wayland display
- Accept one client
- Inspect Evas native-surface capabilities
- Determine feasibility of DMA-BUF buffer import
# Moksha-Warp Environment Setup

## System
Host: MicroForge  
OS: Bodhi Linux (Debian base)

## Installed Packages

The following packages were installed to prepare the development environment:

build-essential  
pkg-config  
python3-dev  
python3-pip  
python3-setuptools  
python3-wheel  
python3-venv  
libefl-dev  
python3-efl  
libwayland-dev  
wayland-protocols  
libdrm-dev  
mesa-utils  
mesa-common-dev  
libegl1-mesa-dev  
libgles2-mesa-dev  

## Python Modules

Verified imports:

- efl
- efl.evas
- efl.elementary
- pywayland

## EFL Versions

pkg-config reports:

- efl: 1.27.0
- evas: 1.27.0
- elementary: 1.27.0
- ecore: 1.27.0

## Notes

Bodhi provides a unified EFL runtime package () version 1.27.0.

Development headers are provided by:

libefl-dev (Bodhi repository)

The Ubuntu package  must **not** be used because it conflicts with the Bodhi runtime packages.

## Current Status

Environment verified.  
Next step: run diagnostic probes for Moksha-Warp.

Scripts to generate:

1. probe_env.py
2. evas_probe.py
3. wayland_probe.py
# Moksha-Warp Current Status

## Date
Thu Mar 12 11:49:19 PM EDT 2026

## Confirmed
- python3-efl imports successfully
- pywayland imports successfully
- pkg-config reports EFL/Evas/Elementary/Ecore version 1.27.0
- EFL headers are available through versioned include directories
- Bodhi-native packages are being used instead of mismatched Ubuntu EFL dev packages

## Current priority
Determine whether Python-EFL exposes native surface APIs usable for later bridge work.

## Next probes
1. probe_env.py
2. evas_probe.py
3. wayland_probe.py
# Moksha-Warp Python-EFL Findings

## Summary
Python-EFL on this Bodhi system exposes Evas image objects and native-surface constants, but does not appear to expose a practical native-surface attachment API for direct DMA-BUF/EGL import from Python.

## Confirmed
- python3-efl imports successfully
- EFL/Evas/Elementary/Ecore version: 1.27.0
- Evas image objects can be created from Python
- Evas native-surface constants are present:
  - EVAS_NATIVE_SURFACE_NONE
  - EVAS_NATIVE_SURFACE_OPENGL
  - EVAS_NATIVE_SURFACE_WL
  - EVAS_NATIVE_SURFACE_X11

## Not Found
- No obvious Python-level native surface attachment method on image objects
- No obvious `native_surface_set` / `native_surface_get`
- No obvious DMA-BUF import path in exposed Python-EFL APIs

## Conclusion
Moksha-Warp should treat Python as the control plane and plan for a small native helper for the zero-copy render/import path.
# Moksha-Warp Wayland Probe Result

## Summary
The Wayland control-plane probe succeeded.

## Confirmed
- pywayland Display() initializes successfully
- A private Wayland socket can be created
- The socket appears under XDG_RUNTIME_DIR
- Observed socket path:
  - /run/user/1000/wayland-warp-0
- Observed lock file:
  - /run/user/1000/wayland-warp-0.lock

## Meaning
Moksha-Warp can host a private Wayland display socket inside the current Moksha/X11 session.

## Current Status
- Environment probe: PASS
- Python-EFL capability probe: PASS
- Native-surface attach path in Python-EFL: NOT FOUND
- Wayland socket probe: PASS

## Conclusion
The Python control plane is viable.
The remaining unknown is the render/import bridge for presenting Wayland client buffers inside Evas.
# Moksha-Warp Client Handshake Result

## Summary
Wayland clients can see and attempt to use the Moksha-Warp socket.

## Tests
### weston-info
Command:
WAYLAND_DISPLAY=wayland-warp-0 weston-info

Result:
- Did not fail with "cannot connect to display"
- Printed deprecation warning
- Then waited until interrupted

Interpretation:
- Client likely connected to the socket
- Moksha-Warp is not yet advertising the protocol globals needed for useful output

### weston-simple-egl
Command:
WAYLAND_DISPLAY=wayland-warp-0 weston-simple-egl

Result:
- Reached EGL initialization path
- Failed with:
  init_egl: Assertion `ret == EGL_TRUE' failed.

Interpretation:
- Client reached deeper negotiation than simple socket discovery
- Moksha-Warp is not yet providing the compositor/rendering environment expected by EGL clients

## Conclusion
Moksha-Warp has successfully moved beyond socket creation into real client handshake territory.

The next phase is to implement minimal compositor globals and basic surface lifecycle support.
# Moksha-Warp SHM Progress

## Summary
The wl_shm global is now advertising valid formats to clients.

## Confirmed
- wl_compositor is advertised
- wl_shm is advertised
- xdg_wm_base is advertised
- wl_shm format events are sent successfully:
  - XRGB8888
  - ARGB8888

## weston-info Result
weston-info now reports:

- interface: wl_compositor
- interface: wl_shm
- formats: XRGB8888 ARGB8888
- interface: xdg_wm_base

## Current Failure
weston-simple-egl still fails after:

- wl_shm.create_pool(...)
- wl_shm_pool.resize(...)

The server then reports:
- invalid object 6

Object 6 is the wl_shm_pool resource.

## Conclusion
The next missing implementation is the server-side wl_shm_pool resource path.
# Moksha-Warp SHM Pool Breakthrough

## Summary
The wl_shm and wl_shm_pool server-side request path is now functioning far enough for a real client to:

- create a shm pool
- resize the shm pool

## Confirmed in Logs
- MyShmResource.create_pool(...)
- MyShmPoolResource.__init__(...)
- MyShmPoolResource.resize(...)

## Meaning
The previous failure at wl_shm_pool has been resolved enough to move the client further into initialization.

## New First Failure
The next missing implementation is now on the xdg shell path:

unknown object (9), message get_xdg_surface(no)

## Conclusion
The next server-side implementation target is xdg_wm_base.get_xdg_surface(...)
# Moksha-Warp XDG Breakthrough

## Summary
Moksha-Warp now handles enough Wayland and xdg-shell protocol to move a real client through:

- wl_compositor.create_surface
- wl_shm.create_pool
- wl_shm_pool.resize
- xdg_wm_base.get_xdg_surface
- xdg_surface.get_toplevel
- xdg_surface.configure
- xdg_surface.ack_configure
- wl_surface.commit

## New First Failure
The next missing implementation is:

unknown object (14), message attach(?oii)

This indicates the next missing server-side object is the wl_buffer path, likely created via wl_shm_pool.create_buffer(...).

## Conclusion
The next implementation target is wl_shm_pool.create_buffer(...) and minimal wl_buffer resource handling.
# Moksha-Warp Night One Status

## Confirmed
Moksha-Warp successfully hosts a private Wayland socket inside the Moksha/X11 session and drives a real client through a substantial portion of the Wayland and xdg-shell protocol.

## Proven Working
- private Wayland socket
- client connection
- global advertisement
- wl_shm format advertisement
- wl_shm_pool creation
- wl_shm_pool resize
- wl_shm_pool create_buffer
- wl_compositor create_surface
- xdg_wm_base get_xdg_surface
- xdg_surface get_toplevel
- xdg_surface configure / ack_configure
- wl_surface attach
- wl_surface commit

## Current Frontier
The remaining work is in server-side buffer consumption, frame/presentation flow, and eventually bridging rendered client output into the X11/Evas side.

## Conclusion
The architecture is real.
The next phase is turning protocol progress into visible output.
# Moksha-Warp Milestone 10
## Wayland Client Render Loop Breakthrough

Date: 2026-03-13

---

# Summary

The moksha-warp prototype has reached a major milestone. A real Wayland client is now able to connect to the prototype server and enter a continuous rendering loop.

This confirms that moksha-warp correctly implements enough of the Wayland protocol to support active frame production from a client.

---

# Test Client

Client used:

weston-simple-egl

Environment:

Bodhi Linux 7  
Moksha desktop (X11)

---

# Confirmed Protocol Flow

The following lifecycle has been verified through logs.

### Global Discovery

wl_display.get_registry  
wl_registry.global  
wl_registry.bind  

Globals exposed by moksha-warp:

wl_compositor  
wl_shm  
xdg_wm_base  

---

### Surface Creation

wl_compositor.create_surface

Creates:

MyWlSurfaceResource

---

### Window Role Negotiation

xdg_wm_base.get_xdg_surface  
xdg_surface.get_toplevel  

Server sends:

xdg_surface.configure  

Client responds:

xdg_surface.ack_configure  

---

### Shared Memory Allocation

The client allocates buffers using the Wayland shared memory interface.

Observed calls:

wl_shm.create_pool  
wl_shm_pool.resize  
wl_shm_pool.create_buffer  

Example buffer parameters:

width  = 250  
height = 250  
stride = 1000  
format = ARGB8888  

Buffers are represented internally as:

MyWlBufferResource

---

# Render Loop Breakthrough

The client now repeatedly executes the following sequence:

wl_surface.frame  
wl_callback.done  
wl_surface.attach  
wl_surface.damage  
wl_surface.commit  

Example logs:

MyWlSurfaceResource.frame id=13  
MyWlCallbackResource.done 1  

MyWlSurfaceResource.attach buffer=<MyWlBufferResource> x=0 y=0  
MyWlSurfaceResource.damage  
MyWlSurfaceResource.commit  

This sequence repeats continuously, confirming the client is actively rendering frames.

---

# Buffer Lifecycle

After each frame commit, the client allocates a new buffer.

Observed pattern:

MyShmPoolResource.create_buffer  
MyWlBufferResource.__init__  

This indicates the client is producing new frame data for every render cycle.

---

# Current Limitation

Buffers are currently received but not displayed.

The server logs the buffer attachment but does not yet read the pixel data or render it to a visible window.

---

# Next Development Step

Implement buffer presentation.

Required tasks:

1. Track attached buffer for each surface
2. Read pixel memory from shm pool
3. Interpret ARGB buffer format
4. Render pixel data to a visible window
5. Maintain the frame callback loop

---

# Significance

This milestone demonstrates that:

- Wayland protocol negotiation works
- XDG shell surfaces function correctly
- Shared memory buffers are created successfully
- Frame callbacks are functioning
- The client render loop is active

The remaining work is focused on displaying the received buffers.

---

# Next Milestone

Milestone 11 will target the first visible frame produced by a Wayland client inside Moksha.
# Moksha-Warp Milestone 11
## First Visible Wayland Client Frame

Date: 2026-03-13

---

# Summary

The moksha-warp prototype has reached the first visible-frame milestone.

A real Wayland client now renders successfully through the prototype bridge, and its shared-memory buffer contents are displayed in a visible preview window running inside the existing Moksha/X11 environment.

This is the first direct proof that moksha-warp can do more than negotiate protocol state. It can now receive client frame data and present it on screen.

---

# Test Client

Client used:

weston-simple-egl

Environment:

Bodhi Linux 7  
Moksha desktop (X11)

---

# Confirmed Rendering Path

The following end-to-end path has now been verified:

Wayland client  
→ moksha-warp Wayland server  
→ wl_shm pool and buffer creation  
→ buffer attach to wl_surface  
→ buffer commit  
→ shm pixel memory read  
→ pygame preview window  
→ visible rendered frame

---

# Confirmed Protocol Flow

The following lifecycle was observed in live logs.

### Global Discovery

wl_display.get_registry  
wl_registry.global  
wl_registry.bind  

Globals exposed by moksha-warp:

wl_compositor  
wl_shm  
xdg_wm_base  

---

### Surface Creation

wl_compositor.create_surface

Creates:

MyWlSurfaceResource

---

### XDG Shell Negotiation

xdg_wm_base.get_xdg_surface  
xdg_surface.get_toplevel  
xdg_toplevel.set_title  
xdg_surface.configure  
xdg_surface.ack_configure  

This confirms the client successfully negotiates a toplevel application surface.

---

### Shared Memory Allocation

The client allocates frame buffers using wl_shm.

Observed calls:

wl_shm.create_pool  
wl_shm_pool.resize  
wl_shm_pool.create_buffer  

Example observed parameters:

width  = 250  
height = 250  
stride = 1000  
format = ARGB8888  

Internal resource types used:

MyShmPoolResource  
MyBufferResource  

---

### Surface Commit Path

The following request sequence is now active and handled:

wl_surface.set_opaque_region  
wl_surface.frame  
wl_surface.attach  
wl_surface.damage  
wl_surface.commit  

The server responds by:

- storing the attached buffer
- promoting it to current buffer on commit
- reading pixel bytes from shm memory
- presenting the result through the preview renderer
- sending frame callback completion

---

# Visible Frame Breakthrough

A visible window now opens and displays output from the Wayland client.

Observed renderer log:

[renderer] window ready 250x250  
[renderer] presented buffer 250x250 stride=1000 offset=0 fmt=0  

This confirms that shm buffer contents are being interpreted and drawn successfully.

The rendered result was a visible colorful triangle from weston-simple-egl.

This is the first successful visual output from a real Wayland client through moksha-warp.

---

# Architecture State At This Milestone

moksha-warp now includes a working prototype path for:

- wl_compositor
- wl_shm
- wl_shm_pool
- wl_buffer
- wl_surface
- wl_callback
- xdg_wm_base
- xdg_surface
- xdg_toplevel

The current renderer backend is:

pygame / SDL preview window

This backend is being used as a fast proof-of-concept presentation layer inside Moksha/X11.

---

# Refactor Progress

After the first visible-frame breakthrough, the working prototype was also moved into a cleaner module structure.

Current package layout includes:

warp/shm_preview_bridge.py  
scripts/run_shm_preview_bridge.py  

This preserves the working render path in a reusable entry point instead of leaving it only in the original probe script.

---

# Remaining Technical Debt

The bridge is now visually functional, but several areas still need improvement.

### 1. shm Pool / Buffer Lifetime

Current behavior keeps shm mmap/fd resources alive after pool destruction so buffers remain usable.

This is acceptable for proof-of-concept validation, but proper ownership tracking is still needed.

Future fix:

- reference counting of buffers per pool
- close mmap/fd only when last dependent buffer is gone

### 2. Resource Cleanup

Exit and destruction behavior should be hardened further for repeated runs and broader client compatibility.

### 3. Surface Management

The current preview path is effectively a direct presentation surface.

Future work must map Wayland surfaces more intentionally into Moksha-managed windows.

### 4. Renderer Abstraction

pygame is suitable for validation, but moksha-warp should eventually expose a renderer abstraction so the backend can be replaced with:

- X11-native rendering
- Evas / EFL integration
- future Moksha-managed presentation

---

# Significance

This milestone demonstrates that:

- Wayland protocol negotiation works
- XDG shell negotiation works
- wl_shm pool and buffer creation works
- wl_surface attach / damage / commit works
- shm pixel memory can be mapped and read
- a real Wayland client frame can be shown on screen
- the core bridge concept is viable

This is the first milestone where moksha-warp stops being a protocol-only experiment and becomes a visible graphics bridge prototype.

---

# Next Development Step

The next engineering target is to replace the current proof-of-concept shm lifetime shortcut with proper pool / buffer ownership management.

That will convert the current first-frame success into a more stable rendering foundation.

---

# Next Milestone

Milestone 12 should target:

proper shm pool lifetime management and renderer/backend abstraction groundwork.
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
# Doc 12 – Free VT Direct Scanout Test

## Objective

Verify whether moksha-warp can perform true direct scanout (zero-copy presentation)
when run outside of an X11 session on a free virtual terminal (VT).

Previous milestones confirmed:

- dmabuf ingestion working
- EGLImage preview path working
- DRM/KMS device discovery working
- dmabuf → DRM framebuffer import working
- direct scanout attempt via drmModeSetCrtc

The VT test removes X11/Wayland session ownership so the compositor
can attempt to become DRM master.

---

# Test Environment

Machine: MicroForge  
GPU: Intel UHD 630 (Mesa)  
Session type: X11 desktop → switched to free VT  
Compositor: moksha-warp (Python / pywayland)

---

# VT Test Procedure

1. Switch to free VT

Ctrl + Alt + F3

2. Run the test script

~/repos/moksha-warp/vt_zero_copy_test.sh

3. Collect logs written to:

logs/proof/vt-zero-copy-*.log  
logs/proof/vt-zero-copy-summary-*.txt  
logs/proof/vt-zero-copy-client-*.log  

---

# Observed Result

The compositor started successfully and DRM/KMS probing worked:

[kms-probe] /dev/dri/card0: crtcs=3 connectors=6  
[kms-probe] DisplayPort-1 connected modes=[1920x1080@60 ...]  
[kms-probe] backend ready, candidate: /dev/dri/card0  

However the EGL importer failed during initialization:

EGL dma-buf importer init failed: eglInitialize failed, eglGetError=0x3001

This caused dmabuf buffer creation to fail:

zwp_linux_buffer_params_v1.create: EGL importer unavailable  
zwp_linux_buffer_params_v1.failed sent import_ok=False  

Client-side output:

Error: zwp_linux_buffer_params.create failed.

---

# Root Cause

The compositor's dmabuf ingestion path currently requires
the EGL importer to be available before accepting dmabuf buffers.

This is incorrect for the direct KMS path.

Direct scanout should operate on raw dmabuf metadata
and does not require EGL at all.

Current flow:

dmabuf received
→ EGLImage import required
→ wl_buffer created

Correct architecture:

dmabuf received
→ store raw dmabuf metadata
→ wl_buffer created

presentation path chosen later:

GLES preview → import EGLImage  
KMS scanout → use raw dmabuf directly  

---

# Conclusion

The VT test successfully exposed the final architectural blocker:

dmabuf ingestion is still coupled to EGL import.

To enable true zero-copy scanout:

- dmabuf acceptance must be independent of EGL
- EGLImage creation must occur lazily only for the GLES preview path

Once this decoupling is implemented,
the direct KMS scanout path should work on a free VT.

---

# Status

| Feature | Status |
|-------|------|
| dmabuf ingestion | working (desktop) |
| EGL preview path | working |
| DRM device discovery | working |
| DRM framebuffer import | working |
| direct scanout attempt | implemented |
| free VT test | completed |
| blocker identified | EGL coupling |

Next milestone: Decouple dmabuf ingestion from EGL importer
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
# Doc 13 – Hardware-Aware Scanout Classification

## Objective

Refine moksha-warp's direct presentation model so scanout decisions are based on
the real KMS mode rather than a temporary fake advertised output size.

This work followed the earlier direct-scanout eligibility prototype and the free-VT
direct presentation experiments.

---

## Key Change

The compositor now distinguishes between three hardware presentation classes:

- PRIMARY_SCANOUT_ELIGIBLE
- PLANE_CANDIDATE
- BLOCKED

This classification uses the actual KMS connector mode size discovered from the
chosen DRM connector/CRTC path.

The previous temporary 256x256 "eligible" test was useful diagnostically, but it
did not represent real primary scanout on a 1920x1080 display mode.

---

## What Changed

### 1. Real hardware mode awareness

The scanout eligibility check no longer relies on fake detector constants such as:

- OUTPUT_WIDTH
- OUTPUT_HEIGHT

Instead, it queries the selected KMS connector information and uses the real mode
size, e.g. 1920x1080.

### 2. Correct presentation class modeling

A dmabuf buffer is now treated as:

- PRIMARY_SCANOUT_ELIGIBLE only if its dimensions match the real mode size
- PLANE_CANDIDATE if it is smaller than the mode but otherwise compatible
- BLOCKED if format/modifier/transform/scale/damage/etc. disqualify it

### 3. EGL decoupling completed

Dmabuf buffer acceptance no longer depends on EGL importer availability.

The compositor now:

- accepts/stores raw dmabuf metadata
- creates the compositor-side wl_buffer resource
- performs EGL import lazily only if the GLES preview path is used

This allows free-VT KMS testing even when EGL is unavailable.

### 4. Better libdrm error decoding

Negative errno-style libdrm returns are now interpreted correctly instead of
logging misleading lines like:

ret=-13 errno=0 (Success)

---

## Desktop Result

For the current 256x256 dmabuf test client on a 1920x1080 mode, moksha-warp now logs:

[direct-scanout] plane-candidate: buffer=256x256 mode=1920x1080 format=XR24 modifier=0  
[scanout] plane-candidate: no overlay plane path yet, using GLES  
[gles] flip done  

This is the correct behavior.

The compositor no longer tries to force a tiny 256x256 surface through
primary CRTC scanout.

---

## Free VT Result

On the free VT, the same 256x256 dmabuf surface now logs:

[direct-scanout] plane-candidate: buffer=256x256 mode=1920x1080 format=XR24 modifier=0  
[scanout] plane-candidate: no overlay plane path yet, using GLES  
[gles] EGL importer unavailable; cannot preview dmabuf  

This is also the correct behavior.

Important points:

- dmabuf buffers are now accepted on VT without EGL
- EGL is no longer blocking dmabuf ingestion
- the compositor correctly recognizes that the 256x256 surface is not a valid
  primary scanout framebuffer for a 1920x1080 mode
- the remaining missing feature for this case is overlay/hardware-plane presentation

---

## Conclusion

Moksha-warp now models hardware presentation honestly:

- fullscreen/mode-sized dmabufs are candidates for primary scanout
- smaller dmabuf windows are candidates for hardware-plane presentation
- incompatible buffers are blocked

This removes the previous fake-win condition and aligns the compositor's decision
logic with real KMS behavior.

---

## Status

| Feature | Status |
|--------|--------|
| dmabuf ingestion decoupled from EGL | working |
| desktop GLES preview fallback | working |
| KMS device/connector/CRTC discovery | working |
| DRM framebuffer import | working |
| primary scanout classification | working |
| plane candidate classification | working |
| free-VT dmabuf acceptance without EGL | working |
| overlay plane presentation | not implemented |
| mode-sized direct primary scanout proof | not yet tested |

Next milestone:
- prove true zero-copy primary scanout with a mode-sized dmabuf buffer, or
- implement overlay-plane presentation for PLANE_CANDIDATE windows
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
