"""Shared automation helpers (no Home Assistant dependency).

Automations don't ship an adapter through getAdapter the way zigbee devices
do — their State descriptors live in the object's attributes. Both the HA
integration and the standalone MQTT bridge need to turn those descriptors into
the same AdapterParam-based pseudo-adapter, so the logic lives here.
"""

from __future__ import annotations

from ..const import AUTOMATION_ENABLED_FIELD
from .models import AdapterParam, DeviceAdapter, DeviceAttributes

# Maps an automation state's datatype string to (param_type, min, max).
# Mirrors DATATYPE_INFO from iot-gate/tg-miniapp/src/components/DeviceCard.jsx.
# Every type carries explicit min/max so HA never falls back to its 0..100
# default (which would clamp signed/large/float values). INT64/UINT64 use the
# JS safe-integer range the TG app uses; FLOAT uses its ±1e6 range.
_SAFE_INT = 2**53 - 1  # Number.MAX_SAFE_INTEGER, matches the TG app
AUTOMATION_DATATYPES: dict[str, tuple[str, int | float, int | float]] = {
    "BOOL":   ("bool",  0, 1),
    "INT8":   ("int",  -128, 127),
    "INT16":  ("int",  -32768, 32767),
    "INT32":  ("int",  -2147483648, 2147483647),
    "INT64":  ("int",  -_SAFE_INT, _SAFE_INT),
    "UINT8":  ("int",  0, 255),
    "UINT16": ("int",  0, 65535),
    "UINT32": ("int",  0, 4294967295),
    "UINT64": ("int",  0, _SAFE_INT),
    "FLOAT":  ("float", -1000000.0, 1000000.0),
}


def build_automation_pseudo_adapter(
    automation_id: str, attrs: DeviceAttributes
) -> DeviceAdapter:
    """Build a synthetic DeviceAdapter from an automation's local States.

    Mirrors what the TG mini-app does (DeviceCard.jsx:42-69) so consumers can
    keep using the existing AdapterParam-driven logic.

    Every automation always gets an "enabled" switch on the virtual field 255
    (its run on/off state), so even automations without any local States still
    show up as a controllable device.
    """
    params: list[AdapterParam] = [
        AdapterParam(
            address=AUTOMATION_ENABLED_FIELD,
            access="rw",
            param_type="bool",
            name="enabled",
            description="Automation enabled",
            view_params={"type": "switch"},
        )
    ]
    for st in attrs.states:
        if not isinstance(st, dict) or st.get("type") != "local":
            continue
        local_id = st.get("localId")
        if local_id is None:
            continue
        datatype = (st.get("datatype") or "").upper()
        param_type, min_v, max_v = AUTOMATION_DATATYPES.get(
            datatype, AUTOMATION_DATATYPES["INT32"]
        )
        writable = bool(st.get("write"))
        name = st.get("name") or f"state_{local_id}"
        params.append(
            AdapterParam(
                address=int(local_id),
                access="rw" if writable else "r",
                param_type=param_type,
                name=name,
                description=st.get("description"),
                min_value=min_v,
                max_value=max_v,
                view_params={"type": "switch" if param_type == "bool" else "value"},
            )
        )
    return DeviceAdapter(
        driver=f"_automation_{automation_id}",
        crc=0,
        description="Pushok automation",
        device_type="automation",
        params=params,
    )
