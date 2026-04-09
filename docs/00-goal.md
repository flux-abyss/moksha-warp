# Moksha-Warp

Experimental nested Wayland bridge for Moksha.

Goal:
Host Wayland-native clients inside a standard Moksha (X11) desktop window using a minimal asynchronous proxy.

Key idea:
Python handles control-plane orchestration while the graphics stack handles buffer import and rendering.

Initial milestone:
- Start private Wayland display
- Accept one client
- Inspect Evas native-surface capabilities
- Determine feasibility of DMA-BUF buffer import
