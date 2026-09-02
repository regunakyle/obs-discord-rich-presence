# PLAN.md — OBS Discord Rich Presence Script

## Goal

An OBS Studio Python script that starts a Discord rich presence when a stream starts and stops it when the stream stops. Connection attempts may fail (e.g. Discord not running) — failures are logged and retried, never fatal to OBS.

## Requirements

1. **OBS script** (`obs_discord_rich_presence.py`):
   - Start rich presence on `OBS_FRONTEND_EVENT_STREAMING_STARTED`.
   - Stop rich presence on `OBS_FRONTEND_EVENT_STREAMING_STOPPED`.
   - Use the `pypresence` library, vendored as a git submodule at `vendor/pypresence/` and bundled next to the script at runtime.
   - Never block the OBS main thread.
2. **Typing**:
   - The OBS Python API has no types, so a hand-written stub file `obspython.pyi` declares only the functions/constants the script uses.
   - `pyright` enforces typing (configured in `pyproject.toml`).
3. **Distribution** (GitHub Actions):
   - Package only the OBS script, the `pypresence` package, a markdown usage guide, the license files, and the README's example screenshot (`ui.png`) into a zip (the GPLv3 license must accompany the distribution, and pypresence's MIT copyright notice must be kept with the vendored package).
   - The script calls `pypresence` directly from the same folder (OBS adds the script directory to `sys.path`).
   - `pypresence` is self-contained (i.e. no third-party dependencies).

## Decisions (confirmed with user)

| Question | Decision |
| --- | --- |
| Configurable presence fields | Full set: Application ID, details, state, large/small image key + tooltip, two buttons (label + URL) |
| Elapsed streaming time | Yes — `start=int(time.time())` at stream start |
| Discord not running at stream start | Retry with exponential backoff — 1 s doubling to a 16 s cap — until connected or stream stops (warning logged at most once a minute) |
| Applying settings while streaming | Explicit **Update Presence** button; typing only snapshots settings |
| Missing Application ID feedback | Warning label in the settings UI (OBS 29.1+, feature-detected) plus the log warning |
| Settings UI layout | Titled groups: Presence text / Images / Buttons |
| Short-string validation | Red error under any presence field holding a single character (Discord requires ≥ 2 chars or empty); empty is treated as unset |
| Error display | Centralized message rows between the setting groups and the update button; the button is disabled while any error/warning is active |
| Clickable text/images | Exposed as URL settings (`details_url`, `state_url`, `large_url`, `small_url`); rendering varies by Discord client — buttons remain the reliable mechanism |
| Workflow trigger | Tag push (`v*`) and manual `workflow_dispatch` |
| Activity type | "Watching" (`ActivityType.WATCHING`) instead of the default "Playing" |
| Application name | Optional "Application name" setting passed through as `name` in the payload; Discord normally shows the Developer Portal name, so rendering is not guaranteed (CustomRP exposes the same field) |

## Architecture

```
OBS main thread                        Worker thread (_PresenceWorker)
────────────────                       ───────────────────────────────
script_load()                          run() loop over command queue:
  - apply saved settings                 START    -> connect with retry,
  - register frontend event callback               then update presence
  - start worker thread                   REFRESH  -> push update() with
script_update(settings)                            latest settings (sent only
  - snapshot settings -> worker                     by the update button; if
    (user typing never touches Discord)             no presence is active, log
"Update Presence" button                       an info message instead)
  - queue REFRESH                         STOP     -> close() presence
frontend event callback                   SHUTDOWN -> close() and exit
  - STREAMING_STARTED  -> queue START
  - STREAMING_STOPPED  -> queue STOP
script_unload()
  - remove event callback
  - queue SHUTDOWN + join
```

Key points:

- **Why a worker thread:** `Presence.connect()` blocks up to its connection timeout. All pypresence calls must stay on one thread (it drives its own asyncio loop), so a single daemon thread owns the client; the OBS thread only enqueues commands.
- **Retry loop:** on connect failure, retry with exponential backoff — the wait doubles after each failure from 1 s up to a 16 s cap and resets on success — while polling the queue so STOP/SHUTDOWN interrupt the wait immediately and end the retry campaign (a stream that stops mid-retry never gets a presence). The warning is logged at most once per minute, and the failed client's asyncio event loop is closed so retries do not leak loops.
- **Send-time validation:** `_push_update` applies the same omission rules as the settings UI (empty omits the field; single-character, over-limit, and byte-over-limit values are invalid). Invalid fields are dropped instead of sent, so one bad field cannot make Discord reject the entire `SET_ACTIVITY` payload on the stream-start path (where no button guards the input); dropped fields are named in a log warning. Button label/URL are stripped before the same rules apply.
- **Rate limit:** Discord accepts one presence update per 15 s. Presence updates only happen on stream start/stop and on explicit user action (the update button), never per keystroke, so rate-limit rejections are rare; a rejected update is caught and logged.
- **New `Presence` instance per connect** (pypresence closes its event loop on `close()`).
- **Settings UI:** the Application ID field lives in its own group ("Discord application") so the top-level form has no labeled rows; its label column then collapses to zero width and the centralized validation messages and the update button start at the left margin (info rows render in the form's field column via `addRow(nullptr, label)`, and Qt's `QFormLayout` sizes that column from the widest label). The Application ID field carries a modified callback that shows/hides an `OBS_TEXT_INFO` warning property while the ID is empty; the warning row sits directly under the Application ID field inside the "Discord application" group (initial visibility comes from the worker's snapshot, since `script_load` applies saved settings before the properties view is built). Info properties need OBS 29.1+ and are feature-detected; older versions get the log warning only. All other validation messages (single-character fields, incomplete buttons) are centralized in rows between the setting groups and the update button, each message naming its field. The update button is disabled (`obs_property_set_enabled`, works on any OBS version) while any message is active. Visibility/enabled callbacks compare the desired state with `obs_property_visible()`/`obs_property_enabled()` and return True only on an actual transition — returning True makes OBS destroy and rebuild the whole properties view (`RefreshProperties`), and the modified callback fires on every keystroke, so an unconditional True caused an abrupt refresh per keystroke.
- **pypresence import:** `from pypresence import Presence` with a fallback that inserts the vendored `vendor/pypresence` folder next to the script into `sys.path`, so the script runs both from a dev checkout and from the distributed zip layout.
- **Streaming state:** queried with `obs_frontend_streaming_active()` on script load so a stream already running when the script is added also gets a presence. The function is available because `obspython.i` SWIG-wraps `obs-frontend-api.h` when `ENABLE_FRONTEND` is set (any standard OBS Studio build); only callback-taking frontend functions are manually re-registered by the scripting layer.
- IPC timeouts set to 10 s (pypresence defaults are 10–30 s) so stream start stays responsive.

## Files

| File | Purpose |
| --- | --- |
| `obs_discord_rich_presence.py` | The OBS script |
| `obspython.pyi` | Type stub for the used subset of `obspython` |
| `README.md` | End-user guide, packaged in the zip |
| `ui.png` | Example screenshot embedded by the README, packaged in the zip |
| `LICENSE.md` | GPL-3.0 license (also declared via SPDX header in the script) |
| `.github/workflows/release.yml` | Packaging/release workflow |
| `pyproject.toml` | pyright config (`stubPath`, `extraPaths: vendor/pypresence`) |
| `vendor/pypresence/` | Git submodule (v4.6.2+), source of the bundled package |

## Verification

- `uv run pyright` — 0 errors (script, stub, vendored pypresence).
- Manual (not yet done): load script in OBS, start/stop stream with Discord running, then with Discord closed to confirm retry and log messages.

## Status

- [x] Type stub `obspython.pyi`
- [x] OBS script with worker thread, retry, elapsed timer, settings UI
- [x] Presence start when script is loaded mid-stream (`obs_frontend_streaming_active()`)
- [x] Two presence buttons (label + URL)
- [x] Application ID warning in the settings UI (OBS 29.1+)
- [x] Explicit "Update Presence" button instead of per-keystroke updates
- [x] Activity type "Watching" instead of "Playing" (`ActivityType.WATCHING`)
- [x] Optional "Application name" setting passed through as `name` (rendering client-dependent)
- [x] Reconnect under a new application when the Application ID changes while live
- [x] Clickable text/images via URL fields (`details_url`, `state_url`, `large_url`, `small_url`)
- [x] Grouped settings UI (Presence text / Images / Buttons)
- [x] Single-character validation errors under every presence field
- [x] Incomplete-button errors (label without URL or URL without label)
- [x] Centralized validation area above the update button
- [x] Update button disabled while any error or the missing-Application-ID warning is active
- [x] Tooltips on every setting field (usage + Discord limits)
- [x] Button-label byte-length validation (32 bytes)
- [x] Max-length validation for all fields (128/256/512 per Discord limits)
- [x] Send-time validation in `_push_update`: invalid or incomplete fields are dropped instead of sent (so one bad field cannot make Discord reject the whole presence); dropped fields are named in a log warning
- [x] `README.md` guide
- [x] `release.yml` packaging workflow (tag + manual dispatch)
- [x] pyright config and clean typecheck
- [ ] Test in Linux

## Possible future work

- Support selecting the Discord IPC pipe (e.g. for PTB/Canary).

Note: `obspython` SWIG-wraps all of `obs.h` and `obs-frontend-api.h` (when `ENABLE_FRONTEND` is set, i.e. every standard OBS Studio build), so most of the libobs/frontend API — e.g. `obs_get_output_by_name`, output signal handlers, `obs_frontend_streaming_active()` — is callable from scripts. Only callback-taking functions are manually re-registered by the scripting layer (`obs-scripting-python-frontend.c`).
