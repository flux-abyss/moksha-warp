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
