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
