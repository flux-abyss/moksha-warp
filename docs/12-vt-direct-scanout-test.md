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
