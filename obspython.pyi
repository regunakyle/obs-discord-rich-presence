"""Type stubs for the subset of the ``obspython`` module used by this script.

The real ``obspython`` module only exists inside OBS Studio.  These
declarations let pyright type-check the script without OBS installed.

Only the functions and constants this script actually calls are declared
here.  See ``obs-studio/docs/sphinx/scripting.rst`` and the OBS frontend
API documentation for the full API.
"""

from collections.abc import Callable
from typing import Any

# -- Log levels (obs.h) -------------------------------------------------

LOG_ERROR: int
LOG_WARNING: int
LOG_INFO: int
LOG_DEBUG: int

# -- Text property types (obs-properties.h) ------------------------------

OBS_TEXT_DEFAULT: int
OBS_TEXT_PASSWORD: int
OBS_TEXT_MULTILINE: int
OBS_TEXT_INFO: int

# -- Text info types (obs-properties.h) ----------------------------------

OBS_TEXT_INFO_NORMAL: int
OBS_TEXT_INFO_WARNING: int
OBS_TEXT_INFO_ERROR: int

# -- Property group types (obs-properties.h) ------------------------------

OBS_GROUP_NORMAL: int
OBS_GROUP_CHECKABLE: int

# -- Frontend events (obs-frontend-api.h) --------------------------------

OBS_FRONTEND_EVENT_STREAMING_STARTED: int
OBS_FRONTEND_EVENT_STREAMING_STOPPED: int

# -- Opaque handle types ---------------------------------------------------

class obs_data_t:
    """Settings data object passed to script callbacks."""

class obs_properties_t:
    """Properties object that defines the script settings UI."""

class obs_property_t:
    """A single property inside a properties object."""

# -- Scripting functions (obspython module) -------------------------------

def script_log(level: int, message: str) -> None:
    """Write a message to the OBS script log."""

def obs_data_get_string(settings: obs_data_t, name: str) -> str:
    """Return the string value of a setting."""

def obs_data_set_default_string(settings: obs_data_t, name: str, value: str) -> None:
    """Set the default string value of a setting."""

def obs_properties_create() -> obs_properties_t:
    """Create a new, empty properties object."""

def obs_properties_add_text(
    properties: obs_properties_t, name: str, description: str, type: int
) -> obs_property_t:
    """Add a text property to a properties object."""

def obs_properties_add_button(
    properties: obs_properties_t,
    name: str,
    text: str,
    callback: Callable[[obs_properties_t, obs_property_t], bool],
) -> obs_property_t:
    """Add a button property.

    ``callback(props, prop)`` is invoked when the button is clicked; a
    True return value refreshes the properties view.
    """

def obs_properties_add_group(
    properties: obs_properties_t,
    name: str,
    description: str,
    type: int,
    group: obs_properties_t,
) -> obs_property_t:
    """Add a group property rendering ``group``'s properties in a titled
    frame."""

def obs_property_name(prop: obs_property_t) -> str:
    """Return the setting name of a property."""

def obs_properties_get(
    properties: obs_properties_t, name: str
) -> obs_property_t | None:
    """Return the property with the given name, or None if absent."""

def obs_property_set_visible(prop: obs_property_t, visible: bool) -> None:
    """Show or hide a property in the properties view."""

def obs_property_visible(prop: obs_property_t) -> bool:
    """Return whether a property is currently visible."""

def obs_property_set_enabled(prop: obs_property_t, enabled: bool) -> None:
    """Enable or disable (grey out) a property's widget."""

def obs_property_enabled(prop: obs_property_t) -> bool:
    """Return whether a property's widget is enabled."""

def obs_property_set_long_description(prop: obs_property_t, description: str) -> None:
    """Set the tooltip of a property."""

def obs_property_text_set_info_type(prop: obs_property_t, type: int) -> None:
    """Set the display style of an OBS_TEXT_INFO property."""

def obs_property_text_set_info_word_wrap(prop: obs_property_t, wrap: bool) -> None:
    """Enable or disable word wrap on an OBS_TEXT_INFO property."""

def obs_property_set_modified_callback(
    prop: obs_property_t,
    callback: Callable[[obs_properties_t, obs_property_t, obs_data_t], bool],
) -> None:
    """Call ``callback(props, prop, settings)`` when the property changes.

    The return value of the callback signals that the properties view
    should be refreshed.
    """

# -- Frontend functions (obspython module) --------------------------------

def obs_frontend_add_event_callback(callback: Callable[[int], Any]) -> None:
    """Register a frontend event callback.

    ``callback`` must be a module-level function and is called with a
    single ``int`` event code (an ``OBS_FRONTEND_EVENT_*`` constant).
    """

def obs_frontend_remove_event_callback(callback: Callable[[int], Any]) -> None:
    """Remove a previously registered frontend event callback."""

def obs_frontend_streaming_active() -> bool:
    """Return True if OBS is currently streaming."""
