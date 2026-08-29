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
  - client_id:    Discord application Client ID (required)
  - details:      First line of the presence
  - state:        Second line of the presence
  - large_image:  Large image key or image URL
  - large_text:   Tooltip for the large image
  - small_image:  Small image key or image URL
  - small_text:   Tooltip for the small image
  - button1_label/button1_url:   First clickable button
  - button2_label/button2_url:   Second clickable button
"""

from __future__ import annotations

import queue
import threading
import time

import obspython as obs
from pypresence import Presence

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

_CLIENT_ID = "client_id"
_DETAILS = "details"
_STATE = "state"
_LARGE_IMAGE = "large_image"
_LARGE_TEXT = "large_text"
_SMALL_IMAGE = "small_image"
_SMALL_TEXT = "small_text"
_BUTTON1_LABEL = "button1_label"
_BUTTON1_URL = "button1_url"
_BUTTON2_LABEL = "button2_label"
_BUTTON2_URL = "button2_url"

_DEFAULTS: dict[str, str] = {
    _CLIENT_ID: "",
    _DETAILS: "Streaming live",
    _STATE: "",
    _LARGE_IMAGE: "",
    _LARGE_TEXT: "",
    _SMALL_IMAGE: "",
    _SMALL_TEXT: "",
    _BUTTON1_LABEL: "",
    _BUTTON1_URL: "",
    _BUTTON2_LABEL: "",
    _BUTTON2_URL: "",
}

# Seconds between retries when Discord is unreachable, e.g. not running.
_RETRY_INTERVAL_SECONDS = 1.0
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
        self._stream_start = 0
        self._last_retry_log = float("-inf")

    # -- Called from the OBS main thread -----------------------------------

    def start_streaming(self) -> None:
        self._commands.put(self._START)

    def stop_streaming(self) -> None:
        self._commands.put(self._STOP)

    def update_settings(self, settings: dict[str, str]) -> None:
        with self._settings_lock:
            self._settings = settings
        self._commands.put(self._REFRESH)

    def shutdown(self) -> None:
        if self.is_alive():
            self._commands.put(self._SHUTDOWN)
            self.join(timeout=_SHUTDOWN_JOIN_SECONDS)

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
                self._push_update()
            elif command == self._STOP:
                self._disconnect()
            elif command == self._SHUTDOWN:
                self._disconnect()
                return

    def _connect_with_retry(self) -> bool:
        """Connect to Discord, retrying while a stream is active.

        Returns True when a shutdown was requested during the retries.
        """
        while True:
            client_id = self._get(_CLIENT_ID).strip()
            if not client_id:
                _log(
                    obs.LOG_WARNING,
                    "No Discord application Client ID is set. "
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
                        f"Retrying every {int(_RETRY_INTERVAL_SECONDS)} second.",
                    )
                if self._wait_or_abort():
                    return True
                continue
            self._presence = presence
            self._push_update()
            _log(obs.LOG_INFO, "Discord rich presence started.")
            return False

    def _wait_or_abort(self) -> bool:
        """Wait out the retry interval while watching for commands.

        Returns True when a shutdown was requested, and False when the
        interval elapsed or streaming stopped.
        """
        deadline = time.monotonic() + _RETRY_INTERVAL_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                command = self._commands.get(timeout=remaining)
            except queue.Empty:
                return False
            if command == self._SHUTDOWN:
                return True
            if command == self._STOP:
                return False
            # START/REFRESH absorbed: the next attempt uses the latest
            # settings, and there is no presence to refresh yet.

    def _push_update(self) -> None:
        presence = self._presence
        if presence is None:
            return
        with self._settings_lock:
            settings = dict(self._settings)
        buttons: list[dict[str, str]] = []
        for label_key, url_key in (
            (_BUTTON1_LABEL, _BUTTON1_URL),
            (_BUTTON2_LABEL, _BUTTON2_URL),
        ):
            label = settings[label_key].strip()
            url = settings[url_key].strip()
            # A button needs both a label and a URL to be valid.
            if label and url:
                buttons.append({"label": label, "url": url})
        try:
            presence.update(
                start=self._stream_start,
                details=settings[_DETAILS] or None,
                state=settings[_STATE] or None,
                large_image=settings[_LARGE_IMAGE] or None,
                large_text=settings[_LARGE_TEXT] or None,
                small_image=settings[_SMALL_IMAGE] or None,
                small_text=settings[_SMALL_TEXT] or None,
                buttons=buttons or None,
            )
        except Exception as error:
            _log(obs.LOG_WARNING, f"Could not update Discord rich presence ({error!r}).")

    def _disconnect(self) -> None:
        presence, self._presence = self._presence, None
        if presence is None:
            return
        try:
            presence.close()
        except Exception as error:
            _log(obs.LOG_WARNING, f"Error while disconnecting from Discord ({error!r}).")
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
        "Requires a Discord application Client ID (see the usage guide) "
        "and the <i>pypresence</i> folder next to this script."
    )


def script_defaults(settings: obs.obs_data_t) -> None:
    for name, value in _DEFAULTS.items():
        obs.obs_data_set_default_string(settings, name, value)


def script_properties() -> obs.obs_properties_t:
    props = obs.obs_properties_create()
    obs.obs_properties_add_text(
        props, _CLIENT_ID, "Discord application Client ID", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _DETAILS, "Details (first line)", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _STATE, "State (second line)", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _LARGE_IMAGE, "Large image (key or URL)", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _LARGE_TEXT, "Large image tooltip", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _SMALL_IMAGE, "Small image (key or URL)", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _SMALL_TEXT, "Small image tooltip", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _BUTTON1_LABEL, "Button 1 label", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _BUTTON1_URL, "Button 1 URL", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _BUTTON2_LABEL, "Button 2 label", obs.OBS_TEXT_NORMAL
    )
    obs.obs_properties_add_text(
        props, _BUTTON2_URL, "Button 2 URL", obs.OBS_TEXT_NORMAL
    )
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
