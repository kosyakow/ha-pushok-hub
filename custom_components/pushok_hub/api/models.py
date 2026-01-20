"""Data models for Pushok Hub API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PropertyValue:
    """Represents a device property value."""

    value: Any
    time: int | None = None
    ack: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PropertyValue:
        """Create PropertyValue from dict."""
        return cls(
            value=data.get("value"),
            time=data.get("time"),
            ack=data.get("ack", False),
        )


@dataclass
class DeviceDescription:
    """Represents a Zigbee device description."""

    id: str  # IEEE address
    manufacturer: str
    model: str
    network_id: int
    driver: str | None = None
    last_seen: int | None = None
    lqi: int | None = None
    warning: bool = False
    has_description: bool = False
    attr_crc: int | None = None
    adapter_crc: int | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceDescription:
        """Create DeviceDescription from API response."""
        return cls(
            id=data["id"],
            manufacturer=data.get("mnf", "Unknown"),
            model=data.get("mdl", "Unknown"),
            network_id=data.get("netid", 0),
            driver=data.get("drv"),
            last_seen=data.get("lse"),
            lqi=data.get("lqi"),
            warning=data.get("warn", False),
            has_description=data.get("desc", False),
            attr_crc=data.get("attr"),
            adapter_crc=data.get("adptr-crc"),
            error=data.get("error"),
        )


@dataclass
class DeviceAttributes:
    """Represents device user-defined attributes."""

    name: str | None = None
    tags: list[str] = field(default_factory=list)
    params_visibility: dict[int, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceAttributes:
        """Create DeviceAttributes from API response."""
        # Handle case where data might not be a dict
        if not isinstance(data, dict):
            return cls(name=None, tags=[], params_visibility={})

        visibility = {}
        if "paramsVisibility" in data:
            pv = data["paramsVisibility"]
            if isinstance(pv, dict):
                for k, v in pv.items():
                    visibility[int(k)] = v

        return cls(
            name=data.get("name"),
            tags=data.get("tags", []),
            params_visibility=visibility,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for API request."""
        return {
            "name": self.name,
            "tags": self.tags,
            "paramsVisibility": {str(k): v for k, v in self.params_visibility.items()},
        }


@dataclass
class DeviceState:
    """Represents device state with all properties."""

    device_id: str
    properties: dict[int, PropertyValue] = field(default_factory=dict)
    adapter_crc: int | None = None

    @classmethod
    def from_dict(cls, device_id: str, data: dict[str, Any]) -> DeviceState:
        """Create DeviceState from API response."""
        properties = {}
        adapter_crc = None

        # Handle case where data might not be a dict
        if not isinstance(data, dict):
            return cls(device_id=device_id, properties={}, adapter_crc=None)

        # Make a copy to avoid modifying original
        data = dict(data)
        adapter_crc = data.pop("adptr-crc", None)

        for key, value in data.items():
            if key.isdigit() and isinstance(value, dict):
                properties[int(key)] = PropertyValue.from_dict(value)

        return cls(
            device_id=device_id,
            properties=properties,
            adapter_crc=adapter_crc,
        )


@dataclass
class FieldFormat:
    """Represents a device field format/metadata."""

    field_id: int
    data_type: int
    access: int
    field_type: int

    @classmethod
    def from_raw(cls, field_id: int, raw: int) -> FieldFormat:
        """Create FieldFormat from raw metadata value."""
        return cls(
            field_id=field_id,
            data_type=raw & 0xFF,
            access=(raw >> 8) & 0xFF,
            field_type=(raw >> 16) & 0xFF,
        )

    @property
    def is_read_only(self) -> bool:
        """Check if field is read-only."""
        return self.access == 0

    @property
    def is_bool(self) -> bool:
        """Check if field is boolean type."""
        from ..const import DATA_TYPE_BOOL
        return self.data_type == DATA_TYPE_BOOL

    @property
    def is_numeric(self) -> bool:
        """Check if field is numeric type."""
        from ..const import DATA_TYPE_FLOAT
        return self.data_type <= DATA_TYPE_FLOAT


@dataclass
class DeviceFormat:
    """Represents device format with all fields."""

    device_id: str
    fields: dict[int, FieldFormat] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, device_id: str, data: dict[str, Any]) -> DeviceFormat:
        """Create DeviceFormat from API response."""
        fields = {}

        # Handle case where data might not be a dict
        if not isinstance(data, dict):
            return cls(device_id=device_id, fields={})

        for key, value in data.items():
            if key.isdigit() and isinstance(value, int):
                field_id = int(key)
                fields[field_id] = FieldFormat.from_raw(field_id, value)

        return cls(device_id=device_id, fields=fields)


@dataclass
class AdapterParam:
    """Represents a parameter definition from device adapter."""

    address: int
    access: str  # "r", "w", "rw", ""
    param_type: str  # "bool", "int", "float"
    name: str | None = None
    description: str | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    labels: dict[str, Any] = field(default_factory=dict)
    view_params: dict[str, Any] = field(default_factory=dict)
    convert: dict[str, Any] | None = None
    ya: Any = None  # Can be string or dict for Yandex Smart Home mapping

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdapterParam:
        """Create AdapterParam from dict."""
        view_params = data.get("viewParams", {})
        return cls(
            address=data["address"],
            access=data.get("access", "r"),
            param_type=data.get("type", "int"),
            name=view_params.get("name"),
            description=data.get("description"),
            min_value=data.get("min"),
            max_value=data.get("max"),
            labels=data.get("labels", {}),
            view_params=view_params,
            convert=data.get("convert"),
            ya=data.get("ya"),
        )

    @property
    def is_readable(self) -> bool:
        """Check if parameter is readable."""
        return "r" in self.access

    @property
    def is_writable(self) -> bool:
        """Check if parameter is writable."""
        return "w" in self.access


@dataclass
class DeviceAdapter:
    """Represents full device adapter with parameters and metadata."""

    driver: str
    crc: int
    description: str | None = None
    device_type: str | None = None
    url: str | None = None
    params: list[AdapterParam] = field(default_factory=list)
    ya_device_type: Any = None  # Yandex device type mapping
    raw_content: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, driver: str, data: dict[str, Any]) -> DeviceAdapter:
        """Create DeviceAdapter from API response.

        Args:
            driver: Driver name (e.g., "contact")
            data: Response from getAdapter command containing "content" and "crc"
        """
        import json

        crc = data.get("crc", 0)
        content_str = data.get("content", "{}")

        # Parse JSON content
        if isinstance(content_str, str):
            content = json.loads(content_str)
        else:
            content = content_str

        params = []
        for param_data in content.get("params", []):
            try:
                params.append(AdapterParam.from_dict(param_data))
            except (KeyError, TypeError):
                continue

        return cls(
            driver=driver,
            crc=crc,
            description=content.get("description"),
            device_type=content.get("type"),
            url=content.get("url"),
            params=params,
            ya_device_type=content.get("ya"),
            raw_content=content,
        )

    def get_param_by_address(self, address: int) -> AdapterParam | None:
        """Get parameter by address."""
        for param in self.params:
            if param.address == address:
                return param
        return None

    def get_param_by_name(self, name: str) -> AdapterParam | None:
        """Get parameter by name."""
        for param in self.params:
            if param.name == name:
                return param
        return None
