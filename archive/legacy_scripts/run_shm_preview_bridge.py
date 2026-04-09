#!/usr/bin/env python3
# Historical shim from before the warp/ package restructure.
# The old flat module warp.shm_preview_bridge is now warp.protocol.compositor.
# This file is kept as a reference; do not use directly.
# Use: python3 -m warp.protocol.compositor
from warp.shm_preview_bridge import main

if __name__ == "__main__":
    main()
