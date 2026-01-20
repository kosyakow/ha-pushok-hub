"""Constants for the Pushok Hub integration."""

from typing import Final

DOMAIN: Final = "pushok_hub"

# Configuration
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USE_SSL: Final = "use_ssl"

# Defaults
DEFAULT_PORT: Final = 3001
DEFAULT_PORT_SSL: Final = 443
DEFAULT_USE_SSL: Final = False

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

# Data Types (from Berry protocol)
DATA_TYPE_BOOL: Final = 0
DATA_TYPE_UINT8: Final = 1
DATA_TYPE_UINT16: Final = 2
DATA_TYPE_UINT32: Final = 3
DATA_TYPE_INT8: Final = 4
DATA_TYPE_INT16: Final = 5
DATA_TYPE_INT32: Final = 6
DATA_TYPE_FLOAT: Final = 7

# Broadcast Events
EVT_OBJECT_UPDATE: Final = "object_update"
EVT_NOTIFICATION: Final = "notification"
EVT_DEVICE_STATE_CHANGE: Final = "device_state_change"

# Timeouts
COMMAND_TIMEOUT: Final = 5.0
RECONNECT_INTERVAL: Final = 10.0

# Storage
STORAGE_KEY_PRIVATE_KEY: Final = "ec_private_key"
STORAGE_KEY_USER_ID: Final = "user_id"
