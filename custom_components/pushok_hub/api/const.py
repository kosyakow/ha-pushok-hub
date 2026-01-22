"""API-specific constants for Pushok Hub."""

from typing import Final

# API Commands
CMD_PUB_KEY: Final = "pubKey"
CMD_CHALLENGE: Final = "challenge"
CMD_AUTHENTICATE: Final = "authenticate"
CMD_ADD_USER: Final = "addUser"
CMD_LIST_OBJECTS: Final = "listObjects"
CMD_GET_STATE: Final = "getState"
CMD_SET_STATE: Final = "setState"
CMD_GET_ATTRIBUTES: Final = "getAttributes"
CMD_SET_ATTRIBUTES: Final = "setAttributes"
CMD_GET_FORMAT: Final = "getFormat"
CMD_GET_ADAPTER: Final = "getAdapter"

# User Roles
ROLE_GUEST: Final = 0
ROLE_ADMIN: Final = 1
ROLE_USER: Final = 2

# Entity Types
ENTITY_TYPE_ZIGBEE: Final = "zigbee"
ENTITY_TYPE_AUTOMATION: Final = "automation"
ENTITY_TYPE_GATEWAY: Final = "gateway"

# Broadcast Events
EVT_OBJECT_UPDATE: Final = "object_update"
EVT_NOTIFICATION: Final = "notification"
EVT_DEVICE_STATE_CHANGE: Final = "device_state_change"

# Timeouts
COMMAND_TIMEOUT: Final = 5.0
RECONNECT_INTERVAL: Final = 10.0
