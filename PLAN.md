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
   - Package only the OBS script, the `pypresence` package, and a markdown usage guide into a zip.
   - The script calls `pypresence` directly from the same folder (OBS adds the script directory to `sys.path`).
   - `pypresence` is self-contained (i.e. no third-party dependencies).

## Decisions (confirmed with user)

| Question | Decision |
| --- | --- |
| Configurable presence fields | Full set: Client ID, details, state, large/small image key + tooltip |
| Elapsed streaming time | Yes — `start=int(time.time())` at stream start |
| Discord not running at stream start | Retry every 1 s until connected or stream stops (warning logged at most once a minute) |
| Workflow trigger | Tag push (`v*`) and manual `workflow_dispatch` |

## Architecture

```
OBS main thread                        Worker thread (_PresenceWorker)
────────────────                       ───────────────────────────────
script_load()                          run() loop over command queue:
  - apply saved settings                 START    -> connect with retry,
  - register frontend event callback               then update presence
  - start worker thread                   REFRESH  -> push update() with
script_update(settings)                            latest settings
  - snapshot settings -> worker           STOP     -> close() presence
frontend event callback                   SHUTDOWN -> close() and exit
  - STREAMING_STARTED  -> queue START
  - STREAMING_STOPPED  -> queue STOP
script_unload()
  - remove event callback
  - queue SHUTDOWN + join
```

Key points:

- **Why a worker thread:** `Presence.connect()` blocks up to its connection timeout. All pypresence calls must stay on one thread (it drives its own asyncio loop), so a single daemon thread owns the client; the OBS thread only enqueues commands.
- **Retry loop:** on connect failure, retry every 1 s while polling the queue so STOP/SHUTDOWN interrupt the retry immediately. The warning is logged at most once per minute, and the failed client's asyncio event loop is closed so retries do not leak loops.
- **Rate limit:** Discord accepts one presence update per 15 s; a REFRESH that arrives too soon raises, is caught, and is logged.
- **New `Presence` instance per connect** (pypresence closes its event loop on `close()`).
- **Streaming state:** queried with `obs_frontend_streaming_active()` on script load so a stream already running when the script is added also gets a presence. The function is available because `obspython.i` SWIG-wraps `obs-frontend-api.h` when `ENABLE_FRONTEND` is set (any standard OBS Studio build); only callback-taking frontend functions are manually re-registered by the scripting layer.
- IPC timeouts set to 10 s (pypresence defaults are 10–30 s) so stream start stays responsive.

## Files

| File | Purpose |
| --- | --- |
| `obs_discord_rich_presence.py` | The OBS script |
| `obspython.pyi` | Type stub for the used subset of `obspython` |
| `README.md` | End-user guide, packaged in the zip |
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
- [x] `README.md` guide
- [x] `release.yml` packaging workflow (tag + manual dispatch)
- [x] pyright config and clean typecheck
- [ ] Manual test in OBS Studio
- [ ] First tagged release (`v0.1.0`) to exercise the workflow

## Possible future work

- Retry-interval as a user setting.
- Support selecting the Discord IPC pipe (e.g. for PTB/Canary).
- Clickable presence text/images via URL fields (`state_url`, `details_url`, `large_url`, `small_url` — supported by pypresence).
  
  Whether current Discord clients render these links for unverified user-created applications is unverified; needs a manual test in a real Discord client before exposing them as settings. Buttons are the guaranteed mechanism and already shipped.

Note: `obspython` SWIG-wraps all of `obs.h` and `obs-frontend-api.h` (when `ENABLE_FRONTEND` is set, i.e. every standard OBS Studio build), so most of the libobs/frontend API — e.g. `obs_get_output_by_name`, output signal handlers, `obs_frontend_streaming_active()` — is callable from scripts. Only callback-taking functions are manually re-registered by the scripting layer (`obs-scripting-python-frontend.c`).
