"""NC (Not Connected) pad detection."""

from __future__ import annotations

from src.models import EdaData, Toeprint

_NC_NET_NAMES = frozenset({"$NONE$", "NC", "NO_CONNECT", ""})


def is_pad_nc(
    toeprint: Toeprint | None,
    eda_data: EdaData | None,
) -> bool:
    """Return True if the pad has no net connection (NC).

    Detection logic (checked in order):
    1. toeprint is None or net_num < 0 → NC
    2. net_num out of range → NC
    3. Net name matches a known NC pattern → NC
    4. Net has no TRC/VIA/PLN subnets (only TOP) → NC
    """
    if toeprint is None:
        return False
    if toeprint.net_num < 0:
        return True
    if eda_data is None:
        return False
    if toeprint.net_num >= len(eda_data.nets):
        return True

    net = eda_data.nets[toeprint.net_num]

    if (net.name or "").strip().upper() in _NC_NET_NAMES:
        return True

    for subnet in net.subnets:
        if subnet.type in ("TRC", "VIA", "PLN"):
            return False

    return True
