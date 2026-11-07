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
REDRAW_INTERVAL_S = 0.5
POLL_INTERVAL_S = 1.0
STALE_AFTER_POLLS = 2.0
LINK_DEADLINE_S = 5.0
KEY_REPEAT_GUARD_S = 0.4
RECONNECT_BACKOFF_S = (1.0, 2.0, 4.0, 8.0)
FAILURE_LIMIT = 3
POLL_MIN_S = 0.2
POLL_MAX_S = 10.0
POLL_CHOICES_S = (0.5, 1.0, 2.0, 5.0)
PORT_CHOICES_TTL_S = 2.0

# Screen.
MIN_WIDTH = 60
MIN_HEIGHT = 16

# Menu frame. Rows and columns are 1-based; the offsets count from the far edge.
RAIL_LEFT_COL = 4
RAIL_RIGHT_FROM_END = 4
BAR_LEFT_COL = 5
BAR_RIGHT_FROM_END = 5

STATUS_ROW = 3
STATUS_COL = 8
BANNER_ROW = 4
LIST_ROW = 5
MENU_ITEM_ROW = 6
LAST_ROW_FROM_END = 1
LAST_LABEL_COL = 8
LAST_TEXT_COL = 16

# Item and field cells: label 8/12, power 20/4, data 24/8, voltage 34/9, current 45/7.
LABEL_COL = 8
LABEL_WIDTH = 12
POWER_COL = 20
POWER_WIDTH = 4
DATA_COL = 24
DATA_WIDTH = 8
VOLTAGE_COL = 34
VOLTAGE_WIDTH = 9
CURRENT_COL = 45
CURRENT_WIDTH = 7

DEVICE_VALUE_COL = 20
DEVICE_BACK_ROW = 13

# Device identity.
VID = "1a86"
PID = "fe0c"
HUB_PID = "8091"
MAX_CHANNELS = 7
PRODUCT_NAME = "HBP_USB2_4CH"
