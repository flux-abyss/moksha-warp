#!/usr/bin/env python3
import inspect
import json
import os

from pywayland.protocol.linux_dmabuf_v1 import (
    ZwpLinuxDmabufV1,
    ZwpLinuxBufferParamsV1,
    ZwpLinuxDmabufFeedbackV1,
)

OUT = os.path.expanduser("~/repos/moksha-warp/logs/dmabuf_signatures.json")


def safe_signature(obj):
    try:
        return str(inspect.signature(obj))
    except Exception as e:
        return f"<signature error: {e!r}>"


def dump_interface(cls):
    data = {
        "class": cls.__name__,
        "version": getattr(cls, "version", None),
        "name": getattr(cls, "name", None),
        "global_class": None,
        "global_class_signature": None,
        "resource_class": None,
        "resource_class_signature": None,
        "requests": [],
        "events": [],
    }

    gc = getattr(cls, "global_class", None)
    if gc is not None:
        data["global_class"] = repr(gc)
        data["global_class_signature"] = safe_signature(gc)

    rc = getattr(cls, "resource_class", None)
    if rc is not None:
        data["resource_class"] = repr(rc)
        data["resource_class_signature"] = safe_signature(rc)

    for msg in getattr(cls, "requests", []) or []:
        data["requests"].append(
            {
                "name": getattr(msg, "name", None),
                "version": getattr(msg, "version", None),
                "arguments": repr(getattr(msg, "arguments", None)),
                "py_func": repr(getattr(msg, "py_func", None)),
            }
        )

    for msg in getattr(cls, "events", []) or []:
        data["events"].append(
            {
                "name": getattr(msg, "name", None),
                "version": getattr(msg, "version", None),
                "arguments": repr(getattr(msg, "arguments", None)),
                "py_func": repr(getattr(msg, "py_func", None)),
            }
        )

    return data


data = {
    "ZwpLinuxDmabufV1": dump_interface(ZwpLinuxDmabufV1),
    "ZwpLinuxBufferParamsV1": dump_interface(ZwpLinuxBufferParamsV1),
    "ZwpLinuxDmabufFeedbackV1": dump_interface(ZwpLinuxDmabufFeedbackV1),
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(json.dumps(data, indent=2))
print(f"\nSaved to {OUT}")
