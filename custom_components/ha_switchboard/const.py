"""Home Assistant integration constants."""

DOMAIN = "ha_switchboard"
CONF_GATEWAY_URL = "gateway_url"
CONF_GATEWAY_TOKEN = "gateway_token"
CONF_PROFILE_REFRESH_MINUTES = "profile_refresh_minutes"

DEFAULT_PROFILE_REFRESH_MINUTES = 15
MIN_PROFILE_REFRESH_MINUTES = 1
MAX_PROFILE_REFRESH_MINUTES = 1440

# Registry events are imported from the owning Home Assistant modules below.
# Their string values are retained only for contract tests running without HA.
try:  # pragma: no cover - imports are exercised in the HA devcontainer
    from homeassistant.core import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
    from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
    from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
    from homeassistant.helpers.floor_registry import EVENT_FLOOR_REGISTRY_UPDATED
    from homeassistant.helpers.label_registry import EVENT_LABEL_REGISTRY_UPDATED

    PROFILE_EVENT_TYPES = (
        EVENT_HOMEASSISTANT_STARTED,
        EVENT_ENTITY_REGISTRY_UPDATED,
        EVENT_DEVICE_REGISTRY_UPDATED,
        EVENT_AREA_REGISTRY_UPDATED,
        EVENT_FLOOR_REGISTRY_UPDATED,
        EVENT_LABEL_REGISTRY_UPDATED,
        "exposure_updated",
        "service_schema_updated",
        "assist_surface_updated",
        "routine_updated",
        "reconnect",
        "restart",
    )
except ImportError:  # pragma: no cover - repository tests do not install HA
    PROFILE_EVENT_TYPES = (
        "homeassistant_started",
        "entity_registry_updated",
        "device_registry_updated",
        "area_registry_updated",
        "floor_registry_updated",
        "label_registry_updated",
        "exposure_updated",
        "service_schema_updated",
        "assist_surface_updated",
        "routine_updated",
        "reconnect",
        "restart",
    )

STATE_CHANGED_EVENT = "state_changed"
