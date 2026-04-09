#!/usr/bin/env python3

import inspect

from pywayland.protocol.wayland.wl_compositor import WlCompositorGlobal
from pywayland.protocol.wayland.wl_shm import WlShmGlobal
from pywayland.protocol.xdg_shell.xdg_wm_base import XdgWmBaseGlobal


def show(obj, name):
    print(f"\n{name}")
    try:
        print("  signature:", inspect.signature(obj))
    except Exception as e:
        print("  signature: <unavailable>", e)

    try:
        print("  __init__:", inspect.signature(obj.__init__))
    except Exception as e:
        print("  __init__: <unavailable>", e)


show(WlCompositorGlobal, "WlCompositorGlobal")
show(WlShmGlobal, "WlShmGlobal")
show(XdgWmBaseGlobal, "XdgWmBaseGlobal")
