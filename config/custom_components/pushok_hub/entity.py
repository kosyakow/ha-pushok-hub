"""Base entity for Pushok Hub integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import DeviceDescription, DeviceAttributes
from .const import DOMAIN
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

        # Unique ID: domain_device-ieee_field-id
        self._attr_unique_id = f"{DOMAIN}_{device.id}_{field_id}"

        # Entity name
        if name_suffix:
            self._attr_name = name_suffix
        else:
            self._attr_name = f"Field {field_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        attrs = self.coordinator.attributes.get(self._device.id)
        name = attrs.name if attrs and attrs.name else self._device.model

        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=name,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            sw_version=self._device.driver,
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
    def _state_value(self):
        """Get current state value for this field."""
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
        """Set field value on the device.

        Args:
            value: Value to set
        """
        await self.coordinator.async_set_device_state(
            self._device.id,
            self._field_id,
            value,
        )
