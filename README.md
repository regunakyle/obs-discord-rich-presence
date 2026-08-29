# OBS Discord Rich Presence

> **Origin note:** this project is mostly LLM-generated, written with human guidance (requirements, decisions, and review).

An [OBS Studio](https://obsproject.com) Python script that shows a **Discord rich presence while you are streaming**.
The presence starts when you start streaming and stops when you stop.

The script talks to your locally running Discord client over its IPC pipe using the bundled, self-contained [pypresence](https://github.com/qwertyquerty/pypresence) library.
No other dependencies are required.

## Features

- Starts/stops automatically with your stream.
- Shows elapsed streaming time (Discord's timer).
- All presence fields (details, state, images) are configurable in the OBS Scripts window.
- Up to two clickable buttons (e.g. `Watch live` linking to your Twitch channel).

## Requirements

> **Platform note:** This script has only been tested on Windows with Python 3.12. It may or may not work on Linux and macOS.

- OBS Studio 21.0 or newer.
- Windows with the **Discord desktop app** running while you stream.
- A Python installation for OBS scripting.

  Any Python version between 3.9 to 3.12 should work.

  Python 3.12 can be downloaded [here](https://www.python.org/downloads/release/python-31210/) (Remember to tick *Add python.exe to PATH*).

## Setup

### 1. Create a Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, give it a name (this is the name shown in your Discord profile) and save.
3. On the **General Information** page, copy the **Application ID** (also called Client ID).

**Optional**: for a custom large/small image, go to **Rich Presence → Art Assets** in the portal and upload images, then use their **asset keys** as the image fields in the script. Image URLs also work.

### 2. Add the script to OBS

1. Download the [release archive](https://github.com/regunakyle/obs-discord-rich-presence/releases) and unzip it anywhere you like.
2. In OBS, open **Tools → Scripts**.
3. On the **Python Settings** tab, set the Python install path, for example `C:\Users\<Username>\AppData\Local\Programs\Python\Python312` (There should be a `python3xx.dll` file inside the folder).
4. On the **Scripts** tab, click **+** and select `obs_discord_rich_presence.py`.

### 3. Configure the script

With the script selected, fill in the settings:

| Setting | Meaning |
| --- | --- |
| Discord application Client ID | The Application ID from [step 1](#1-create-a-discord-application) (required) |
| Details | First line of the presence, e.g. `Streaming live` |
| State | Second line of the presence, e.g. `Just chatting` |
| Large image (key or URL) | Large profile image |
| Large image tooltip | Text shown when hovering the large image |
| Small image (key or URL) | Small corner image |
| Small image tooltip | Text shown when hovering the small image |
| Button 1 label / Button 1 URL | First clickable button under the presence, e.g. `Watch live` + `https://twitch.tv/yourchannel` |
| Button 2 label / Button 2 URL | Second clickable button |

Empty fields are simply left out of the presence. A button is only shown when both its label and URL are set; Discord displays at most two buttons. Clicking a button opens the URL in the viewer's browser.

Note: buttons are the only click mechanism that Discord reliably supports for user-created applications. (pypresence also supports clickable presence text/images via URL fields, but support for that varies by Discord version and application, so this script does not expose it.)

## How it behaves

- **Stream start:** the script connects to Discord and sets the presence with an elapsed-time timer.
- **Discord not running:** a warning is written to the script log and the script retries every second until it connects or you stop streaming.
  
  The warning itself is only logged once a minute to keep the log readable.
- **Changing settings while live:** the presence is updated with the new values.

  Note that Discord only accepts one presence update per 15 seconds — if you change settings faster, a warning is logged and the update is dropped.
- **Stream stop:** the presence is cleared and the connection closed.
- All messages appear in the script log at the bottom of the Scripts window and in the main OBS log file (`Tools → Log Files`).

## Troubleshooting

- **Nothing happens:** check the script log for warnings. The most common cause is a missing or wrong Client ID.
- **`Could not connect to Discord (...)`:** make sure the Discord desktop app is running and logged in. The script keeps retrying.
- **Script does not load at all:** the Python path in the Scripts window is wrong, missing, or has the wrong architecture (64-bit OBS needs 64-bit Python).
- **Buttons don't show:** this is a known Discord bug — you cannot see your own buttons, but other users can. Ask a friend (or a second account) to check.
- **Images do not show:** use the exact asset key from the Rich Presence → Art Assets page (not the file name), or a direct image URL.

  New assets can take a few minutes to become available.

## License

This script is licensed under the **GNU General Public License v3**; see [LICENSE.md](./LICENSE.md).

`pypresence` is bundled unmodified and is licensed under the MIT license; its license text is included as `pypresence/LICENSE`.
