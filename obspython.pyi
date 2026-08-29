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

OBS_TEXT_NORMAL: int
OBS_TEXT_MULTILINE: int
OBS_TEXT_PASSWORD: int

# -- Frontend events (obs-frontend-api.h) --------------------------------

OBS_FRONTEND_EVENT_STREAMING_STARTED: int
OBS_FRONTEND_EVENT_STREAMING_STOPPED: int

# -- Opaque handle types ---------------------------------------------------

class obs_data_t:
    """Settings data object passed to script callbacks."""

class obs_properties_t:
    """Properties object that defines the script settings UI."""

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
) -> None:
    """Add a text property to a properties object."""

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
