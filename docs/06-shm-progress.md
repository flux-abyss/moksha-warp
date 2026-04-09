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
