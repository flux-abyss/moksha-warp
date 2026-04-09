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
