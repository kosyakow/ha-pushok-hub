"""Base entity for Pushok Hub integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import AdapterParam, DeviceAdapter, DeviceDescription
from .const import DOMAIN, UNIT_MAPPING
from .coordinator import PushokHubCoordinator


class PushokHubEntity(CoordinatorEntity[PushokHubCoordinator]):
    """Base entity for Pushok Hub devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PushokHubCoordinator,
        device: DeviceDescription,
        field_id: int,
        name_suffix: str | None = None,
    ) -> None:
        """Initialize the entity.

        Args:
            coordinator: Data coordinator
            device: Device description
            field_id: Field ID for this entity
            name_suffix: Optional name suffix for the entity
        """
        super().__init__(coordinator)

        self._device = device
        self._field_id = field_id
        self._adapter_param: AdapterParam | None = None

        # Try to get adapter param info
        adapter = coordinator.get_adapter_for_device(device.id)
        if adapter:
            self._adapter_param = adapter.get_param_by_address(field_id)

        # Unique ID: domain_device-ieee_field-id
        self._attr_unique_id = f"{DOMAIN}_{device.id}_{field_id}"

        # Entity name - prefer adapter param name
        if name_suffix:
            self._attr_name = name_suffix
        elif self._adapter_param and self._adapter_param.name:
            # Capitalize first letter for display
            self._attr_name = self._adapter_param.name.replace("_", " ").title()
        else:
            self._attr_name = f"Field {field_id}"

    @property
    def adapter_param(self) -> AdapterParam | None:
        """Get the adapter parameter info for this entity."""
        return self._adapter_param

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        attrs = self.coordinator.attributes.get(self._device.id)
        name = attrs.name if attrs and attrs.name else self._device.model

        # Get device type from adapter if available
        adapter = self.coordinator.get_adapter_for_device(self._device.id)
        hw_version = adapter.device_type if adapter else None

        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=name,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            sw_version=self._device.driver,
            hw_version=hw_version,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.client or not self.coordinator.client.connected:
            return False

        # Check if device has recent data
        if self._device.warning:
            return False

        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes from adapter."""
        if not self._adapter_param:
            return None

        attrs = {}
        if self._adapter_param.description:
            attrs["description"] = self._adapter_param.description
        if self._adapter_param.min_value is not None:
            attrs["min_value"] = self._adapter_param.min_value
        if self._adapter_param.max_value is not None:
            attrs["max_value"] = self._adapter_param.max_value

        return attrs if attrs else None

    def _get_ha_unit(self) -> str | None:
        """Get Home Assistant unit from adapter viewParams."""
        if not self._adapter_param:
            return None

        unit = self._adapter_param.view_params.get("unit")
        if unit:
            return UNIT_MAPPING.get(unit, unit)
        return None

    def _convert_from_device(self, value: Any) -> Any:
        """Convert value from device using adapter conversion rules.

        Args:
            value: Raw value from device

        Returns:
            Converted value for display
        """
        if value is None:
            return None

        # Don't convert booleans - they don't need conversion
        if isinstance(value, bool):
            return value

        if not self._adapter_param or not self._adapter_param.convert:
            return value

        conversion = self._adapter_param.convert.get("conversion")
        if not conversion:
            return value

        return self._apply_conversion(value, conversion)

    def _convert_to_device(self, value: Any) -> Any:
        """Convert value to device using adapter inversion rules.

        Args:
            value: Value from HA

        Returns:
            Converted value for device
        """
        if value is None:
            return None

        if not self._adapter_param or not self._adapter_param.convert:
            return value

        inversion = self._adapter_param.convert.get("inversion")
        if not inversion:
            return value

        return self._apply_conversion(value, inversion)

    def _apply_conversion(self, value: Any, rules: list) -> Any:
        """Apply conversion rules to a value.

        Conversion rules are in RPN (Reverse Polish Notation) format:
        ["self", 10.0, "/"] means: value / 10.0
        ["self", 100.0, "*"] means: value * 100.0

        Args:
            value: Input value
            rules: Conversion rules list

        Returns:
            Converted value
        """
        if not rules:
            return value

        stack = []
        for item in rules:
            if item == "self":
                stack.append(float(value))
            elif isinstance(item, (int, float)):
                stack.append(float(item))
            elif item == "+":
                b, a = stack.pop(), stack.pop()
                stack.append(a + b)
            elif item == "-":
                b, a = stack.pop(), stack.pop()
                stack.append(a - b)
            elif item == "*":
                b, a = stack.pop(), stack.pop()
                stack.append(a * b)
            elif item == "/":
                b, a = stack.pop(), stack.pop()
                stack.append(a / b if b != 0 else 0)

        return stack[0] if stack else value

    @property
    def _state_value(self):
        """Get current state value for this field (with conversion)."""
        if not self.coordinator.data:
            return None

        state = self.coordinator.data.get(self._device.id)
        if not state:
            return None

        prop = state.properties.get(self._field_id)
        if not prop:
            return None

        return self._convert_from_device(prop.value)

    @property
    def _raw_state_value(self):
        """Get current raw state value for this field (without conversion)."""
        if not self.coordinator.data:
            return None

        state = self.coordinator.data.get(self._device.id)
        if not state:
            return None

        prop = state.properties.get(self._field_id)
        if not prop:
            return None

        return prop.value

    async def _async_set_value(self, value) -> None:
        """Set field value on the device (with conversion).

        Args:
            value: Value to set
        """
        converted_value = self._convert_to_device(value)
        await self.coordinator.async_set_device_state(
            self._device.id,
            self._field_id,
            converted_value,
        )
