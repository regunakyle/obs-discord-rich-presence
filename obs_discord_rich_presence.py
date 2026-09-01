# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Eric Leung
"""Discord Rich Presence for OBS Studio.

Shows a Discord rich presence while OBS is streaming.  The presence is
started when streaming starts and stopped when streaming stops.  The
script talks to the locally running Discord client through its IPC pipe
via the bundled ``pypresence`` package (which must sit in the same
folder as this script).

All pypresence calls run on a dedicated worker thread so that a slow or
missing IPC connection never blocks the OBS main thread.  Failures are
logged to the OBS script log; connection attempts are retried while a
stream is running.

Settings (configured in Tools -> Scripts):
  - client_id:    Discord Application ID (required)
  - name:         Optional application name override (client-dependent)
  - details:      First line of the presence
  - state:        Second line of the presence
  - large_image:  Large image key or image URL
  - large_text:   Tooltip for the large image
  - small_image:  Small image key or image URL
  - small_text:   Tooltip for the small image
  - details_url:  Link opened when clicking the details text
  - state_url:    Link opened when clicking the state text
  - large_url:    Link opened when clicking the large image
  - small_url:    Link opened when clicking the small image
  - button1_label/button1_url:   First clickable button
  - button2_label/button2_url:   Second clickable button
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from pathlib import Path

try:
    from pypresence import ActivityType, Presence
except ImportError:
    # For development: Fall back to the pypresence copy vendored next to this script.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "pypresence"))
    from pypresence import ActivityType, Presence

import obspython as obs

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

_CLIENT_ID = "client_id"
_NAME = "name"
_DETAILS = "details"
_DETAILS_URL = "details_url"
_STATE = "state"
_STATE_URL = "state_url"
_LARGE_IMAGE = "large_image"
_LARGE_TEXT = "large_text"
_LARGE_URL = "large_url"
_SMALL_IMAGE = "small_image"
_SMALL_TEXT = "small_text"
_SMALL_URL = "small_url"
_BUTTON1_LABEL = "button1_label"
_BUTTON1_URL = "button1_url"
_BUTTON2_LABEL = "button2_label"
_BUTTON2_URL = "button2_url"

_DEFAULTS: dict[str, str] = {
    _CLIENT_ID: "",
    _NAME: "",
    _DETAILS: "",
    _DETAILS_URL: "",
    _STATE: "",
    _STATE_URL: "",
    _LARGE_IMAGE: "",
    _LARGE_TEXT: "",
    _LARGE_URL: "",
    _SMALL_IMAGE: "",
    _SMALL_TEXT: "",
    _SMALL_URL: "",
    _BUTTON1_LABEL: "",
    _BUTTON1_URL: "",
    _BUTTON2_LABEL: "",
    _BUTTON2_URL: "",
}

# Warning shown in the script settings UI while no Application ID is set.
# Info-type text properties require OBS 29.1+; older versions only get
# the log warning.
_CLIENT_ID_WARNING = "client_id_warning"
_CLIENT_ID_MISSING_MESSAGE = (
    "No Discord Application ID is set — rich presence will not "
    "start until one is entered above."
)
_INFO_PROPERTIES_SUPPORTED = hasattr(obs, "OBS_TEXT_INFO") and hasattr(
    obs, "obs_property_text_set_info_type"
)

# Property groups in the settings UI.
_APPLICATION_GROUP = "application_group"
_TEXT_GROUP = "text_group"
_IMAGES_GROUP = "images_group"
_BUTTONS_GROUP = "buttons_group"

# Centralized validation messages, shown between the setting groups
# and the update button.  A field holding a single character is
# invalid: Discord rejects presence strings shorter than two
# characters, and empty means the field is unset.
_ERROR_SUFFIX = "_error"
_SINGLE_CHAR_MESSAGE = (
    "{label}: a single character is not allowed — leave the field empty "
    "or enter at least two characters."
)

# Human-readable labels for every presence field, used in the messages.
_FIELD_LABELS: dict[str, str] = {
    _NAME: "Application Name",
    _DETAILS: "Details",
    _DETAILS_URL: "Details URL",
    _STATE: "State",
    _STATE_URL: "State URL",
    _LARGE_IMAGE: "Large Image",
    _LARGE_TEXT: "Large Image Tooltip",
    _LARGE_URL: "Large Image URL",
    _SMALL_IMAGE: "Small Image",
    _SMALL_TEXT: "Small Image Tooltip",
    _SMALL_URL: "Small Image URL",
    _BUTTON1_LABEL: "Button 1 Label",
    _BUTTON1_URL: "Button 1 URL",
    _BUTTON2_LABEL: "Button 2 Label",
    _BUTTON2_URL: "Button 2 URL",
}

# Tooltips (long descriptions) for the setting fields.
_FIELD_TOOLTIPS: dict[str, str] = {
    _NAME: "Optional name sent with the presence. Discord normally "
    "shows the application name configured in the Developer Portal; "
    "Two to 256 characters; empty omits the field.",
    _DETAILS: "First line of the presence text, shown under the "
    "application name. Two to 128 characters; empty omits the line.",
    _DETAILS_URL: "Link opened when the viewer clicks the details text. "
    "Up to 256 characters.",
    _STATE: "Second line of the presence text. Two to 128 characters; "
    "empty omits the line.",
    _STATE_URL: "Link opened when the viewer clicks the state text. "
    "Up to 256 characters.",
    _LARGE_IMAGE: "Large profile image: the asset key from the "
    "application's Rich Presence art assets (two to 32 characters), "
    "or a direct image URL (up to 256 characters).",
    _LARGE_TEXT: "Text shown when hovering the large image. Two to 128 characters.",
    _LARGE_URL: "Link opened when the viewer clicks the large image. "
    "Up to 256 characters.",
    _SMALL_IMAGE: "Small corner image: the asset key from the "
    "application's Rich Presence art assets (two to 32 characters), "
    "or a direct image URL (up to 256 characters).",
    _SMALL_TEXT: "Text shown when hovering the small image. Two to 128 characters.",
    _SMALL_URL: "Link opened when the viewer clicks the small image. "
    "Up to 256 characters.",
    _BUTTON1_LABEL: "Label of the first clickable button under the "
    "presence. Up to 32 bytes; the button is only shown when both "
    "label and URL are set.",
    _BUTTON1_URL: "Link opened when the viewer clicks the first button. "
    "Up to 512 characters.",
    _BUTTON2_LABEL: "Label of the second clickable button under the "
    "presence. Up to 32 bytes; the button is only shown when both "
    "label and URL are set.",
    _BUTTON2_URL: "Link opened when the viewer clicks the second button. "
    "Up to 512 characters.",
}

# Incomplete-button errors: a button needs both a label and a URL; one
# without the other means the button is left out of the presence.
_BUTTON1_ERROR = "button1_error"
_BUTTON2_ERROR = "button2_error"
_BUTTON_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    (_BUTTON1_LABEL, _BUTTON1_URL, _BUTTON1_ERROR, "Button 1"),
    (_BUTTON2_LABEL, _BUTTON2_URL, _BUTTON2_ERROR, "Button 2"),
)
_INCOMPLETE_BUTTON_MESSAGE = (
    "{name} is incomplete — a button needs both a label and a URL and is "
    "left out of the presence until both are set."
)

# The update button, disabled while any setting is in an error state.
_UPDATE_BUTTON = "update_presence"

# Button labels are limited to 32 bytes (UTF-8), not 32 characters —
# characters outside ASCII count as more than one byte.
_BYTES_ERROR_SUFFIX = "_bytes_error"
_FIELD_BYTE_LIMITS: dict[str, int] = {
    _BUTTON1_LABEL: 32,
    _BUTTON2_LABEL: 32,
}
_BYTES_MESSAGE = (
    "{label}: too long — Discord limits button labels to 32 bytes, and "
    "characters outside ASCII count as more than one byte."
)

# Maximum lengths in characters, following Discord's payload limits.
# Image fields accept asset keys or URLs, so they get the URL limit.
_LENGTH_ERROR_SUFFIX = "_length_error"
_FIELD_LENGTH_LIMITS: dict[str, int] = {
    _NAME: 256,
    _DETAILS: 128,
    _STATE: 128,
    _LARGE_TEXT: 128,
    _SMALL_TEXT: 128,
    _LARGE_IMAGE: 256,
    _SMALL_IMAGE: 256,
    _DETAILS_URL: 256,
    _STATE_URL: 256,
    _LARGE_URL: 256,
    _SMALL_URL: 256,
    _BUTTON1_URL: 512,
    _BUTTON2_URL: 512,
}
_LENGTH_MESSAGE = "{label}: too long — the limit is {limit} characters."

# Delay before the first retry when Discord is unreachable, e.g. not
# running.  Doubles after each failure, bounded by _RETRY_MAX_SECONDS.
_RETRY_INTERVAL_SECONDS = 1.0
# Upper bound of the retry backoff.
_RETRY_MAX_SECONDS = 16.0
# How often the retry warning is written to the log; retrying happens far
# more often than logging, otherwise the log would fill up.
_RETRY_LOG_INTERVAL_SECONDS = 60.0
# Seconds to wait for the IPC pipe / Discord responses before failing.
_IPC_TIMEOUT_SECONDS = 10.0
# Seconds to wait for the worker thread to finish on unload.
_SHUTDOWN_JOIN_SECONDS = 10.0


def _log(level: int, message: str) -> None:
    """Write a message to the OBS script log (safe from any thread)."""
    obs.script_log(level, f"[discord rich presence] {message}")


# --------------------------------------------------------------------------
# Presence worker
# --------------------------------------------------------------------------


class _PresenceWorker(threading.Thread):
    """Owns the pypresence client and runs all blocking IPC calls.

    pypresence drives its own asyncio event loop from whichever thread
    calls it, so every call must happen on this one thread.  The OBS
    main thread only ever puts commands on the queue.
    """

    _START = "start"
    _STOP = "stop"
    _REFRESH = "refresh"
    _SHUTDOWN = "shutdown"

    def __init__(self) -> None:
        super().__init__(name="obs-discord-rich-presence", daemon=True)
        self._commands: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._settings_lock = threading.Lock()
        self._settings: dict[str, str] = dict(_DEFAULTS)
        self._presence: Presence | None = None
        self._connected_client_id = ""
        self._stream_start = 0
        self._last_retry_log = float("-inf")

    # -- Called from the OBS main thread -----------------------------------

    def start_streaming(self) -> None:
        self._commands.put(self._START)

    def stop_streaming(self) -> None:
        self._commands.put(self._STOP)

    def update_settings(self, settings: dict[str, str]) -> None:
        """Store the latest settings snapshot.

        The presence is not touched here; the values are applied at the
        next stream start or when apply_now() is called (the settings UI
        "Update presence" button).
        """
        with self._settings_lock:
            self._settings = settings

    def apply_now(self) -> None:
        """Push the current settings to Discord immediately."""
        self._commands.put(self._REFRESH)

    def shutdown(self) -> None:
        if self.is_alive():
            self._commands.put(self._SHUTDOWN)
            self.join(timeout=_SHUTDOWN_JOIN_SECONDS)

    def client_id(self) -> str:
        """Return the currently configured Application ID (trimmed)."""
        return self._get(_CLIENT_ID).strip()

    def settings_snapshot(self) -> dict[str, str]:
        """Return a copy of the current settings."""
        with self._settings_lock:
            return dict(self._settings)

    # -- Worker loop ---------------------------------------------------------

    def run(self) -> None:
        while True:
            command = self._commands.get()
            if command == self._START:
                if self._presence is None:
                    self._stream_start = int(time.time())
                    if self._connect_with_retry():
                        return
            elif command == self._REFRESH:
                if (
                    self._presence is not None
                    and self.client_id() != self._connected_client_id
                ):
                    # The user changed the Application ID while live: rebuild
                    # the connection under the new application.
                    _log(
                        obs.LOG_INFO, "Application ID changed; reconnecting to Discord."
                    )
                    self._disconnect()
                    if self._connect_with_retry():
                        return
                elif self._presence is None:
                    _log(
                        obs.LOG_INFO,
                        "Rich presence is not active; the settings apply "
                        "when streaming starts.",
                    )
                else:
                    self._push_update()
            elif command == self._STOP:
                self._disconnect()
            elif command == self._SHUTDOWN:
                self._disconnect()
                return

    def _connect_with_retry(self) -> bool:
        """Connect to Discord, retrying while a stream is active.

        Retries back off exponentially: the wait doubles after each
        failure, up to _RETRY_MAX_SECONDS, and resets on success (or on
        the next connect campaign, since ``delay`` is local).

        Returns True when a shutdown was requested during the retries;
        False when connected or when streaming stopped meanwhile.
        """
        delay = _RETRY_INTERVAL_SECONDS
        while True:
            client_id = self.client_id()
            if not client_id:
                _log(
                    obs.LOG_WARNING,
                    "No Discord Application ID is set. "
                    "Open the script settings and enter one.",
                )
                return False
            presence: Presence | None = None
            try:
                presence = Presence(
                    client_id,
                    connection_timeout=_IPC_TIMEOUT_SECONDS,
                    response_timeout=_IPC_TIMEOUT_SECONDS,
                )
                presence.connect()
            except Exception as error:  # pypresence raises many exception types
                # A failed connect() never closes the client's event loop,
                # so close it here to avoid piling up loops while retrying.
                if presence is not None:
                    presence.loop.close()
                if (
                    time.monotonic() - self._last_retry_log
                    >= _RETRY_LOG_INTERVAL_SECONDS
                ):
                    self._last_retry_log = time.monotonic()
                    _log(
                        obs.LOG_WARNING,
                        f"Could not connect to Discord ({error!r}). "
                        f"Retrying in {delay:g} seconds.",
                    )
                interrupt = self._wait_or_abort(delay)
                if interrupt == self._SHUTDOWN:
                    return True
                if interrupt == self._STOP:
                    # Streaming stopped before a connection succeeded:
                    # end the retry campaign.  There is no presence to
                    # close yet.
                    _log(
                        obs.LOG_INFO,
                        "Streaming stopped before Discord could be "
                        "reached; rich presence is not started.",
                    )
                    return False
                delay = min(delay * 2.0, _RETRY_MAX_SECONDS)
                continue
            self._presence = presence
            self._connected_client_id = client_id
            self._push_update()
            _log(obs.LOG_INFO, "Discord rich presence started.")
            return False

    def _wait_or_abort(self, delay: float) -> str | None:
        """Wait out the retry delay while watching for commands.

        Returns None when the delay elapsed, or the interrupting command
        (``_STOP`` or ``_SHUTDOWN``) when it arrived first.
        """
        deadline = time.monotonic() + delay
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                command = self._commands.get(timeout=remaining)
            except queue.Empty:
                return None
            if command in (self._STOP, self._SHUTDOWN):
                return command
            # START/REFRESH absorbed: the next attempt uses the latest
            # settings, and there is no presence to refresh yet.

    def _push_update(self) -> None:
        presence = self._presence
        if presence is None:
            return
        with self._settings_lock:
            settings = dict(self._settings)
        skipped: list[str] = []

        def field(key: str) -> str | None:
            """Return the value to send, or None when it must be omitted.

            Mirrors the settings UI validation: empty omits the field,
            and invalid values (a single character, or over the length
            limit) are dropped instead of sent, so one bad field cannot
            make Discord reject the entire presence.  Dropped fields
            are named in a log warning.
            """
            value = settings[key]
            if not value:
                return None
            if len(value) == 1 or len(value) > _FIELD_LENGTH_LIMITS.get(
                key, len(value)
            ):
                skipped.append(_FIELD_LABELS[key])
                return None
            return value

        buttons: list[dict[str, str]] = []
        for label_key, url_key, _error_key, name in _BUTTON_PAIRS:
            label = settings[label_key].strip()
            url = settings[url_key].strip()
            if not label and not url:
                continue
            # The same rules as the settings UI: a button needs both a
            # label and a URL, each long enough and short enough.
            if (
                not label
                or not url
                or len(label) == 1
                or len(url) == 1
                or len(label.encode("utf-8")) > _FIELD_BYTE_LIMITS[label_key]
                or len(url) > _FIELD_LENGTH_LIMITS[url_key]
            ):
                skipped.append(name)
                continue
            buttons.append({"label": label, "url": url})
        if skipped:
            _log(
                obs.LOG_WARNING,
                "Skipped invalid or incomplete settings: "
                + ", ".join(skipped)
                + ". The presence was sent without them.",
            )
        try:
            presence.update(
                # "Watching <application>" instead of "Playing".
                activity_type=ActivityType.WATCHING,
                start=self._stream_start,
                name=field(_NAME),
                details=field(_DETAILS),
                details_url=field(_DETAILS_URL),
                state=field(_STATE),
                state_url=field(_STATE_URL),
                large_image=field(_LARGE_IMAGE),
                large_text=field(_LARGE_TEXT),
                large_url=field(_LARGE_URL),
                small_image=field(_SMALL_IMAGE),
                small_text=field(_SMALL_TEXT),
                small_url=field(_SMALL_URL),
                buttons=buttons or None,
            )
        except Exception as error:
            _log(
                obs.LOG_WARNING, f"Could not update Discord rich presence ({error!r})."
            )

    def _disconnect(self) -> None:
        presence, self._presence = self._presence, None
        if presence is None:
            return
        try:
            presence.close()
        except Exception as error:
            _log(
                obs.LOG_WARNING, f"Error while disconnecting from Discord ({error!r})."
            )
        else:
            _log(obs.LOG_INFO, "Discord rich presence stopped.")

    def _get(self, key: str) -> str:
        with self._settings_lock:
            return self._settings[key]


# --------------------------------------------------------------------------
# OBS script entry points
# --------------------------------------------------------------------------

_worker = _PresenceWorker()


def script_description() -> str:
    return (
        "Shows a Discord rich presence while streaming.<br/><br/>"
        "Requires a Discord Application ID (see README.md)."
    )


def script_defaults(settings: obs.obs_data_t) -> None:
    for name, value in _DEFAULTS.items():
        obs.obs_data_set_default_string(settings, name, value)


def _add_info_row(
    properties: obs.obs_properties_t,
    key: str,
    message: str,
    style: int,
    visible: bool,
) -> None:
    """Add a word-wrapped info message row, shown or hidden."""
    row = obs.obs_properties_add_text(properties, key, message, obs.OBS_TEXT_INFO)
    obs.obs_property_text_set_info_type(row, style)
    obs.obs_property_text_set_info_word_wrap(row, True)
    obs.obs_property_set_visible(row, visible)


def _add_text_field(
    properties: obs.obs_properties_t, key: str, description: str
) -> None:
    """Add a text field with a tooltip and change tracking."""
    field = obs.obs_properties_add_text(
        properties, key, description, obs.OBS_TEXT_DEFAULT
    )
    obs.obs_property_set_modified_callback(field, _on_field_modified)
    tooltip = _FIELD_TOOLTIPS.get(key)
    if tooltip is not None:
        obs.obs_property_set_long_description(field, tooltip)


def _current_values(settings: obs.obs_data_t) -> dict[str, str]:
    """Read all setting values from the settings object."""
    return {key: obs.obs_data_get_string(settings, key) for key in _DEFAULTS}


def _settings_have_errors(values: dict[str, str]) -> bool:
    """Return whether any setting is in an error state."""
    if not values[_CLIENT_ID].strip():
        return True
    for key in _FIELD_LABELS:
        if len(values[key]) == 1:
            return True
    for key, limit in _FIELD_BYTE_LIMITS.items():
        if len(values[key].encode("utf-8")) > limit:
            return True
    for key, limit in _FIELD_LENGTH_LIMITS.items():
        if len(values[key]) > limit:
            return True
    for label_key, url_key, _error_key, _name in _BUTTON_PAIRS:
        if bool(values[label_key]) != bool(values[url_key]):
            return True
    return False


def _toggle_update_button(props: obs.obs_properties_t, values: dict[str, str]) -> bool:
    """Enable or disable the update button based on the error state.

    Returns True when the state changed, so the caller can request a
    view refresh.
    """
    button_prop = obs.obs_properties_get(props, _UPDATE_BUTTON)
    if button_prop is None:
        return False
    should_enable = not _settings_have_errors(values)
    if obs.obs_property_enabled(button_prop) == should_enable:
        return False
    obs.obs_property_set_enabled(button_prop, should_enable)
    return True


def _toggle_info_row(props: obs.obs_properties_t, key: str, should_show: bool) -> bool:
    """Show or hide a message row.

    Returns True when the visibility changed, so the caller can request
    a view refresh.
    """
    row = obs.obs_properties_get(props, key)
    if row is None:
        return False
    if obs.obs_property_visible(row) == should_show:
        return False
    obs.obs_property_set_visible(row, should_show)
    return True


def script_properties() -> obs.obs_properties_t:
    props = obs.obs_properties_create()

    # script_load() applies the saved settings before the properties
    # view is built, so the worker already knows the current values.
    values = _worker.settings_snapshot()

    # The Application ID sits in its own group so that the top-level form has
    # no labeled rows: the label column then collapses to zero width and
    # the validation messages below start at the left margin.
    application_group = obs.obs_properties_create()
    client_id_prop = obs.obs_properties_add_text(
        application_group, _CLIENT_ID, "Application ID", obs.OBS_TEXT_DEFAULT
    )
    obs.obs_property_set_long_description(
        client_id_prop,
        "The Application ID of your Discord application from the Developer Portal.",
    )
    obs.obs_property_set_modified_callback(client_id_prop, _on_client_id_modified)
    # The missing-ID warning sits directly under the Application ID field,
    # inside the same group (obs_properties_get finds properties inside
    # groups, so the callback can still toggle it).
    if _INFO_PROPERTIES_SUPPORTED:
        _add_info_row(
            application_group,
            _CLIENT_ID_WARNING,
            _CLIENT_ID_MISSING_MESSAGE,
            obs.OBS_TEXT_INFO_WARNING,
            not values[_CLIENT_ID].strip(),
        )
    _add_text_field(application_group, _NAME, "Application Name")
    obs.obs_properties_add_group(
        props,
        _APPLICATION_GROUP,
        "Discord Application",
        obs.OBS_GROUP_NORMAL,
        application_group,
    )

    text_group = obs.obs_properties_create()
    _add_text_field(text_group, _DETAILS, "Details")
    _add_text_field(text_group, _DETAILS_URL, "Details URL")
    _add_text_field(text_group, _STATE, "State")
    _add_text_field(text_group, _STATE_URL, "State URL")
    obs.obs_properties_add_group(
        props, _TEXT_GROUP, "Presence Text", obs.OBS_GROUP_NORMAL, text_group
    )

    images_group = obs.obs_properties_create()
    _add_text_field(images_group, _LARGE_IMAGE, "Large Image")
    _add_text_field(images_group, _LARGE_TEXT, "Large Image Tooltip")
    _add_text_field(images_group, _LARGE_URL, "Large Image URL")
    _add_text_field(images_group, _SMALL_IMAGE, "Small Image")
    _add_text_field(images_group, _SMALL_TEXT, "Small Image Tooltip")
    _add_text_field(images_group, _SMALL_URL, "Small Image URL")
    obs.obs_properties_add_group(
        props, _IMAGES_GROUP, "Images", obs.OBS_GROUP_NORMAL, images_group
    )

    buttons_group = obs.obs_properties_create()
    _add_text_field(buttons_group, _BUTTON1_LABEL, "Button 1 Label")
    _add_text_field(buttons_group, _BUTTON1_URL, "Button 1 URL")
    _add_text_field(buttons_group, _BUTTON2_LABEL, "Button 2 Label")
    _add_text_field(buttons_group, _BUTTON2_URL, "Button 2 URL")
    obs.obs_properties_add_group(
        props, _BUTTONS_GROUP, "Buttons", obs.OBS_GROUP_NORMAL, buttons_group
    )

    # Centralized validation messages, between the groups and the button.
    if _INFO_PROPERTIES_SUPPORTED:
        for key, label in _FIELD_LABELS.items():
            _add_info_row(
                props,
                key + _ERROR_SUFFIX,
                _SINGLE_CHAR_MESSAGE.format(label=label),
                obs.OBS_TEXT_INFO_ERROR,
                len(values[key]) == 1,
            )
        for key, limit in _FIELD_BYTE_LIMITS.items():
            _add_info_row(
                props,
                key + _BYTES_ERROR_SUFFIX,
                _BYTES_MESSAGE.format(label=_FIELD_LABELS[key]),
                obs.OBS_TEXT_INFO_ERROR,
                len(values[key].encode("utf-8")) > limit,
            )
        for key, limit in _FIELD_LENGTH_LIMITS.items():
            _add_info_row(
                props,
                key + _LENGTH_ERROR_SUFFIX,
                _LENGTH_MESSAGE.format(label=_FIELD_LABELS[key], limit=limit),
                obs.OBS_TEXT_INFO_ERROR,
                len(values[key]) > limit,
            )
        for label_key, url_key, error_key, name in _BUTTON_PAIRS:
            _add_info_row(
                props,
                error_key,
                _INCOMPLETE_BUTTON_MESSAGE.format(name=name),
                obs.OBS_TEXT_INFO_ERROR,
                bool(values[label_key]) != bool(values[url_key]),
            )

    update_button = obs.obs_properties_add_button(
        props, _UPDATE_BUTTON, "Update Presence", _on_update_button_clicked
    )
    obs.obs_property_set_long_description(
        update_button,
        "Push the current settings to Discord immediately. "
        "Disabled while the settings contain errors.",
    )
    obs.obs_property_set_enabled(update_button, not _settings_have_errors(values))
    return props


def script_update(settings: obs.obs_data_t) -> None:
    _worker.update_settings(
        {key: obs.obs_data_get_string(settings, key) for key in _DEFAULTS}
    )


def script_load(settings: obs.obs_data_t) -> None:
    # Apply saved settings before any event can arrive.
    script_update(settings)
    obs.obs_frontend_add_event_callback(_on_frontend_event)
    _worker.start()
    # The script may be loaded while a stream is already running.
    if obs.obs_frontend_streaming_active():
        _log(
            obs.LOG_INFO,
            "Streaming is already active; starting Discord rich presence.",
        )
        _worker.start_streaming()


def script_unload() -> None:
    obs.obs_frontend_remove_event_callback(_on_frontend_event)
    _worker.shutdown()


def _on_frontend_event(event: int) -> None:
    if event == obs.OBS_FRONTEND_EVENT_STREAMING_STARTED:
        _worker.start_streaming()
    elif event == obs.OBS_FRONTEND_EVENT_STREAMING_STOPPED:
        _worker.stop_streaming()


def _on_client_id_modified(
    props: obs.obs_properties_t, prop: obs.obs_property_t, settings: obs.obs_data_t
) -> bool:
    """Update the Application ID warning and the update button state."""
    refresh = _toggle_info_row(
        props,
        _CLIENT_ID_WARNING,
        not obs.obs_data_get_string(settings, _CLIENT_ID).strip(),
    )
    if _toggle_update_button(props, _current_values(settings)):
        refresh = True
    return refresh


def _on_field_modified(
    props: obs.obs_properties_t, prop: obs.obs_property_t, settings: obs.obs_data_t
) -> bool:
    """Update the centralized error rows and the update button state.

    A refresh is only requested (True) when a visibility or enabled
    state actually changed, because True makes OBS rebuild the whole
    properties view.
    """
    key = obs.obs_property_name(prop)
    value = obs.obs_data_get_string(settings, key)
    refresh = False

    if _toggle_info_row(props, key + _ERROR_SUFFIX, len(value) == 1):
        refresh = True

    byte_limit = _FIELD_BYTE_LIMITS.get(key)
    if byte_limit is not None and _toggle_info_row(
        props, key + _BYTES_ERROR_SUFFIX, len(value.encode("utf-8")) > byte_limit
    ):
        refresh = True

    length_limit = _FIELD_LENGTH_LIMITS.get(key)
    if length_limit is not None and _toggle_info_row(
        props, key + _LENGTH_ERROR_SUFFIX, len(value) > length_limit
    ):
        refresh = True

    for label_key, url_key, error_key, _name in _BUTTON_PAIRS:
        if key not in (label_key, url_key):
            continue
        label = obs.obs_data_get_string(settings, label_key)
        url = obs.obs_data_get_string(settings, url_key)
        # Exactly one of the two filled in: the button is incomplete.
        if _toggle_info_row(props, error_key, bool(label) != bool(url)):
            refresh = True

    if _toggle_update_button(props, _current_values(settings)):
        refresh = True
    return refresh


def _on_update_button_clicked(
    props: obs.obs_properties_t, prop: obs.obs_property_t
) -> bool:
    """Apply the current settings to the rich presence immediately."""
    _worker.apply_now()
    return False
