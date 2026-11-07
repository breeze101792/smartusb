"""Snapshots, frames and plain text shared by the host tests."""

from hubctl.app.view import ANSI_RE, render
from hubctl.hal.base import (
    ChannelReading,
    Identity,
    LinkState,
    Mode,
    Snapshot,
    Status,
)

SELECTED = "\x1b[1;7m"
PRODUCT = "HBP_USB2_4CH"


def readings(channels=4):
    values = {number: ChannelReading(True, True, 4614, 0)
              for number in range(1, channels + 1)}
    if channels >= 2:
        values[2] = ChannelReading(False, None, 202, 0)
    if channels >= 3:
        values[3] = ChannelReading(True, False, 5020, 210)
    if channels >= 4:
        values[4] = ChannelReading(True, True, 4880, 440)
    return values


def make_snapshot(link=LinkState.LIVE, mode=Mode.NORMAL, age=0.4,
                  action="USB2 off - echo ok, 0x00 off, 0x08 off",
                  kind="ok", reconnect=None, channels=4, product=PRODUCT,
                  poll=1.0, port=None, port_choices=()):
    identity = Identity(product, 0, "V1.3", "V2.0", channels, 5,
                        "/dev/ttyACM0")
    return Snapshot(
        identity=identity,
        status=Status(mode, True, False),
        channels=readings(channels),
        link=link,
        last_cycle_age_s=age,
        last_action=action,
        last_kind=kind,
        reconnect_in_s=reconnect,
        poll_interval_s=poll,
        port_setting=port,
        port_choices=port_choices,
    )


def make_no_device():
    return Snapshot(
        identity=None,
        status=Status(Mode.UNKNOWN),
        channels={},
        link=LinkState.LOST,
        last_cycle_age_s=0.0,
        last_action="no SmartUSBHub CMD port found; connect the CMD cable",
        last_kind="err",
        reconnect_in_s=4.0,
    )


def frame(snapshot, state, width=80, height=24, **options):
    return render(snapshot, state, width, height, **options)


def plain(lines):
    return [ANSI_RE.sub("", line) for line in lines]
