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
