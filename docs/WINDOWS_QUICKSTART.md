# Windows quick start

[中文版](WINDOWS_QUICKSTART.zh-CN.md) · [What this fork changes](FORK_CHANGES.md)

From a fresh clone to "hold the blue button, speak, text appears in the window you are typing in". The upstream guide
(`docs/USAGE.zh-CN.md`) is written for macOS; this one is for Windows 10/11. It was checked on one Windows 10 PC —
if a step does not match your machine, please open an issue.

**Why you must build the firmware yourself:** your Wi-Fi name / password, the PC's address and the shared token are
compiled into the firmware (`vibe_stick_secrets.h`). There is no generic pre-built binary to download.

## What you need

| | |
|---|---|
| M5Stack **StickS3** + a USB-C **data** cable | A charge-only cable will not be detected |
| A **2.4 GHz** Wi-Fi network | The ESP32-S3 cannot join 5 GHz. A router that merges both bands under one name is usually fine |
| Windows 10/11 PC on the **same LAN** | PC and device must be able to reach each other (no "client isolation", see the end) |
| Python **3.11+** for the bridge | `py -3 --version` |
| Git, ≈ 3 GB of disk for ESP-IDF | |
| Speech recognition | Either a cloud API key (the default is [SiliconFlow](https://cloud.siliconflow.cn)) **or** the offline model ([FORK_CHANGES §5](FORK_CHANGES.md#5-voice-input)) |

## 1. Get the code and create your two private files

```powershell
git clone <this repository's URL> VibeStick
cd VibeStick
Copy-Item firmware\sticks3\include\vibe_stick_secrets.example.h firmware\sticks3\include\vibe_stick_secrets.h
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"      # your token: copy the output
ipconfig                                                       # note this PC's IPv4 address on the Wi-Fi/LAN adapter
```

Both new files are git-ignored. Do not commit them and do not post them.

Edit `firmware\sticks3\include\vibe_stick_secrets.h`:

```c
#define VIBE_STICK_WIFI_SSID "your 2.4 GHz network name"
#define VIBE_STICK_WIFI_PASSWORD "its password"
#define VIBE_STICK_BRIDGE_HOST "192.168.1.23"      // this PC's IPv4 address
#define VIBE_STICK_BRIDGE_PORT 8765
#define VIBE_STICK_BRIDGE_TOKEN "the token you just generated"
```

Edit `.env` (at least these; the **same token** as above):

```ini
VIBE_STICK_BRIDGE_TOKEN=the token you just generated
VIBE_STICK_RECORDING_USE_MAC_MIC=0        # required on Windows
VIBE_STICK_ASR_API_KEY=your SiliconFlow key   # or configure local recognition instead
VIBE_STICK_COMPUTER_NAME=MyPC             # shown on the device (ASCII only)
```

## 2. Install ESP-IDF 5.5 (once)

```powershell
git clone -b v5.5.1 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git C:\esp\esp-idf
cd C:\esp\esp-idf
# optional, helps if github.com downloads are slow or blocked for you:
# $env:IDF_GITHUB_ASSETS = 'dl.espressif.cn/github_assets'
.\install.ps1 esp32s3
```

The installer builds its own Python environment from whichever Python is first on your `PATH`. We used **Python
3.12** (and did not try 3.14); if the install complains about your Python, put a 3.12/3.13 first on `PATH`.

## 3. Build and flash

Open a new PowerShell for each session and load the environment first:

```powershell
. C:\esp\esp-idf\export.ps1
cd <your clone>\firmware\sticks3
idf.py build                       # first build downloads components, needs internet
```

Plug in the StickS3 and find its port (Device Manager → *Ports*: "USB Serial Device (COMx)" / "USB JTAG/serial
debug unit"), then:

```powershell
idf.py -p COM4 flash
```

- Normally the tool puts the chip into download mode by itself. If it sticks at `Connecting...`, hold the power
  button until the blue LED double-blinks and the screen goes dark, then run the command again.
- After flashing, unplug and replug (or press the power button). The home screen appears; it shows "offline" until the bridge runs.
- Changing Wi-Fi, address or token later means building and flashing again.

## 4. Install and run the bridge

From the repository root (the folder that contains `.env`; the bridge reads `.env` from the current folder):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install .\bridge
# offline recognition (optional): .\.venv\Scripts\python -m pip install "./bridge[local-asr]"
.\.venv\Scripts\python -m vibe_stick --host 0.0.0.0 --port 8765
```

It prints `VibeStick Bridge listening on http://0.0.0.0:8765` and the device's requests. Leave the window open.

### Allow it through the Windows firewall

The first run may ask for permission; if not, or if the device stays offline, add rules in an **administrator**
PowerShell (replace the subnet with your own, e.g. `192.168.1.0/24`):

```powershell
New-NetFirewallRule -DisplayName "VibeStick TCP 8765" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Any -RemoteAddress 192.168.1.0/24
New-NetFirewallRule -DisplayName "VibeStick UDP 8766" -Direction Inbound -Protocol UDP -LocalPort 8766 -Action Allow -Profile Any -RemoteAddress 192.168.1.0/24
```

Gotcha we hit: a leftover **Block** rule for `python.exe` on the *Public* profile (created when you once clicked
"Cancel" on the firewall prompt) beats every Allow rule. List them with
`Get-NetFirewallRule -Direction Inbound | ? DisplayName -eq 'python.exe' | select DisplayName,Profile,Action,Enabled`
and disable the Block rule.

Quick test that does not need the device: open `http://<this PC's IP>:8765/health` in a phone browser on the same
Wi-Fi. If the phone cannot open it, the device cannot either.

## 5. Try it

1. The device screen should leave "offline" within ~10 seconds.
2. Click into any text box, **hold the blue button**, wait for the two-tone cue, speak, release.
3. The transcript is pasted. A `timing …` line in the bridge window shows where the time went.

Controls, battery behaviour and everything else that differs from upstream: [FORK_CHANGES.md](FORK_CHANGES.md).

## 6. Running in the background

- Upstream's `scripts\install_windows.ps1` creates a hidden per-user scheduled task and a venv under
  `%APPDATA%\VibeStick` (and **copies the repository's `.env` over `%APPDATA%\VibeStick\.env` every time you run it**).
  On the PC of this fork's author those tasks did not start (error `0x80070002`) for a reason we never pinned down;
  it may work for you.
- If it does not: keep the bridge in a terminal, or start `pythonw.exe -m vibe_stick --host 0.0.0.0 --port 8765`
  from a Startup-folder shortcut / a task whose *Start in* folder is the one containing `.env` (not tested by us).
- Remember: if the PC sleeps the device is disconnected.

## Troubleshooting

| Symptom | Check |
|---|---|
| Device stays "offline" | PC IP unchanged? (`ipconfig`, give it a fixed IP) · firewall rules / the `python.exe` Block rule · phone test above · 2.4 GHz · router "AP / client isolation" or guest network · some networks refuse WPA3-only for ESP32 devices (not verified) |
| Flash stuck at `Connecting...` | Data cable? Download mode (power button, blue LED double-blink) · another program holding the COM port |
| Speech never appears | Bridge window: `local ASR …` / `recording stop result …` lines · `VIBE_STICK_RECORDING_USE_MAC_MIC=0` · API key · focus is in a text box |
| Quota shows `--%` or `Upd 15h ago` | Claude Code login expired → [FORK_CHANGES §6](FORK_CHANGES.md#6-claude-usage-freshness-and-self-healing-login) |
| Edited `.env` but nothing changes | The bridge reads `%APPDATA%\VibeStick\.env` **before** `.\.env`; delete the stale copy |
| Device vanished after the PC slept | Expected; wake the PC and it reconnects (search again with a long press of the right button if the IP changed) |
