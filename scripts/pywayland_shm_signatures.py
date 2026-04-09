#!/usr/bin/env python3

import inspect

from pywayland.protocol.wayland.wl_shm import WlShmGlobal, WlShm, WlShmResource
from pywayland.protocol.wayland.wl_shm_pool import WlShmPool, WlShmPoolResource


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
    print("  dir:")
    for item in dir(obj):
        if "pool" in item.lower() or "format" in item.lower() or "create" in item.lower() or "bind" in item.lower():
            print("   -", item)


show(WlShmGlobal, "WlShmGlobal")
show(WlShm, "WlShm")
show(WlShmResource, "WlShmResource")
show(WlShmPool, "WlShmPool")
show(WlShmPoolResource, "WlShmPoolResource")
