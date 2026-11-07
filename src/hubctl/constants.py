"""Timing, limits and platform constants.

Everything the behaviour depends on is named here. Values that come from the
hardware documentation say so; the rest are chosen and justified in
docs/architecture/overview.md.
"""

BAUD = 115200

# Serial timing.
ACK_TIMEOUT_S = 0.20
MULTI_TIMEOUT_S = 0.35
DRAIN_WINDOW_S = 0.02
WRITE_SETTLE_S = 0.03
WRITE_TIMEOUT_S = 0.20

# App timing.
TICK_MS = 50
POLL_INTERVAL_S = 1.0
STALE_AFTER_POLLS = 2.0
LINK_DEADLINE_S = 5.0
KEY_REPEAT_GUARD_S = 0.4
RECONNECT_BACKOFF_S = (1.0, 2.0, 4.0, 8.0)
FAILURE_LIMIT = 3

# Screen.
MIN_WIDTH = 60
MIN_HEIGHT = 16
SMALL_HEIGHT = 20

# Device identity.
VID = "1a86"
PID = "fe0c"
HUB_PID = "8091"
MAX_CHANNELS = 7
