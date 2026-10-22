# What this fork changes

[中文版](FORK_CHANGES.zh-CN.md) · [Windows quick start](WINDOWS_QUICKSTART.md)

This is a Windows-focused fork of [VibeStick](https://github.com/GaryGaryyy/VibeStick) (via
[280342193/VibeStick-1](https://github.com/280342193/VibeStick-1), which added the Windows bridge). The upstream
project and its licence are kept; everything below is what was **added or changed on top of it**.

Everything here was built and tested on **one** setup: a Windows 10 PC (Ryzen 7 2700, 32 GB), one M5Stack StickS3,
ESP-IDF 5.5.1. Numbers are measurements from that setup, not guarantees. Where something is an estimate or was not
verified, it says so.

- [1. Controls](#1-controls)
- [2. Screen](#2-screen)
- [3. Battery](#3-battery)
- [4. Sounds](#4-sounds)
- [5. Voice input](#5-voice-input)
- [6. Claude usage: freshness and self-healing login](#6-claude-usage-freshness-and-self-healing-login)
- [7. Bridge fixes and performance](#7-bridge-fixes-and-performance)
- [8. New configuration](#8-new-configuration)
- [9. Build, flash, test](#9-build-flash-test)
- [10. Known limitations](#10-known-limitations)

---

## 1. Controls

The StickS3 has three keys: the **blue front button**, the **right-side button**, and the **power button** on the
left side (portrait, screen facing you).

| Key | Gesture | Action |
|---|---|---|
| Blue front button | **Hold** (fires after 300 ms) | Soft two-tone cue, then record while held; release to transcribe and paste |
| Blue front button | Single click | Press **Enter** on the computer (send what was just pasted) |
| Blue front button | Double click | Refresh the quota now (otherwise every 5 min) |
| Blue front button | Any gesture while the screen is **off** | Only wakes the screen; the gesture itself is swallowed |
| Right button | **Single click** | **Screen on / off** (while the computer picker is open: *next computer*) |
| Right button | **Double click** | **Switch page**: Codex → Claude → DeepSeek balance → Codex |
| Right button | **Triple click** | **Portrait ⇄ landscape** (remembered across reboots) |
| Right button | Hold (450 ms) | Search for bridges on the LAN (computer picker) |
| Left power button | Single click | Does nothing (the power-management chip would otherwise **restart** the device; the firmware now disables that) |
| Left power button | **Double click** | **Power off** (handled by the chip; it is its default behaviour, we only keep it enabled). Turn on again with one click |
| Left power button | Hold | Enter download mode for flashing (until the blue LED double-blinks); see the flashing guide |

Notes

- Because a single click on the right button has to be told apart from a double / triple click, it reacts after a
  short delay (a fraction of a second). That is the price of three gestures on one key.
- While a recording is in progress the right button never blanks the screen.
- In the computer picker: right button = next, blue button = choose (same as upstream).
- Upstream used a single click on the right button to switch provider; that moved to **double click**.

## 2. Screen

**It never turns off by itself.** Upstream turned the backlight off after 5 s of inactivity; that made the device
useless as a desk display. Now the screen stays on until you press the right button once. It lights up again on
its own when an alert arrives (task finished / error / waiting for approval), and when you press any key.

Trade-off: a lit screen costs battery. With a 250 mAh battery you should either keep it on USB power or switch the
screen off when you carry it (see [Battery](#3-battery)).

### Orientation

Triple-click the right button to rotate between portrait (135×240) and landscape (240×135, blue button on the
right). The choice is stored in flash (`nvs`, key `orient`).

Landscape layout:

```
[icon] Claude                  ● Running
5H  ━━━━━━━━━━━━━━━━━━━━━━━   87%
7D  ━━━━━━━━━━━━━━━━━━━━━━━   93%
WiFi         Upd 3m ago           🔋 65%
```

The recording overlay and the computer picker have landscape layouts too. The quota block (rounded frame and
divider) is replaced by two full-width bars in landscape.

### "Updated N ago" line

The bottom line used to show the computer name. When the bridge reports quota numbers it now shows **how old those
numbers are**:

| Age | Text | Colour |
|---|---|---|
| < 1 min | `Upd <1m ago` | white |
| 1–59 min | `Upd 5m ago` | white up to 10 min, **amber** after |
| 1 h – 2 days | `Upd 15h ago` | **red** |
| > 2 days | `Upd 3d ago` | red |

The age is counted on the **device's own clock**, starting from the value the bridge sent, so it keeps growing even
if the bridge or the computer disappears. With a healthy bridge it cycles between `<1m` and `5m` (the bridge refreshes
every 5 minutes). Amber means refreshing is not getting through; red usually means the Claude login expired
([section 6](#6-claude-usage-freshness-and-self-healing-login)). When no age is available (Codex, or no data yet) the
line falls back to the computer name.

## 3. Battery

### Facts about the hardware

- The StickS3 has a **250 mAh** battery, roughly 5 % of a phone battery.
- Espressif/M5 figures (4.2 V): power off 14 µA, ESP32 asleep ≈ 102 µA, active (Wi-Fi on) ≈ 37 mA, full load ≈ 519 mA.
- This firmware keeps Wi-Fi connected so it can answer a key press immediately and show alerts. Measured on our
  unit (full battery unplugged, screen **off**, state polled every 5 s): it ran **about 6.5 hours** before it shut
  down at 2.96 V, i.e. roughly 40 mA average. The screen is not the main cost — with the screen on part of the time
  the voltage fell at the same ≈ 145 mV/h. (An earlier version of this document said ≈ 15 h; that was an estimate
  from a log with a gap and was wrong.) We found no sign of a faulty battery.
- Since then the firmware has an **eco mode and a battery policy**, see below. We have not yet measured how much
  they help; the log will tell.
- Practical advice: **keep it plugged in** when using it as a desk device. It is not a pocket device with this firmware.
- The official *Hat 18650C* battery base is listed by some shops as compatible, but M5Stack's own StickS3 page says it
  is structurally **incompatible**. A power bank on the USB-C port is the realistic way to extend runtime.
- A charger that holds the USB input at ≈ 5.1–5.2 V charged the battery normally. A PC USB port that sagged to
  ≈ 4.65 V showed the charging flag almost always at 0. We only have a few minutes of comparison data for that, so
  treat it as a hint, not a result.

### Power saving and low-battery behaviour

`firmware/sticks3/src/vibe_power.c` (pure C, unit-tested on a PC):

- **Eco mode** = no USB power, screen off, not recording. The device then asks the bridge for its state every
  **20 s** instead of 5 s, samples the battery every **60 s** instead of 15 s, and switches Wi-Fi to the deeper
  `WIFI_PS_MAX_MODEM`. Cost: a "done" sound can arrive up to ~20 s late while in eco mode.
- **Auto power-off:** 30 minutes in a row in eco mode → the device powers off through the PMIC (single click on the
  power button turns it on). Any key press, USB power, or an alert that lights the screen restarts the countdown.
- **Low battery:** at ≤ 10 % and again at ≤ 5 % (once each per discharge) the error tone plays and the screen lights
  for 8 s; at ≤ 2 % on two consecutive samples the device powers off instead of running down to the PMIC cut-off.
  Plugging in USB rearms the warnings.
- The thresholds are constants in `vibe_power.h`. Power-off through the PMIC (`SYS_CMD 0xA1`) follows the M5PM1
  register map from M5Stack's library; check it on your unit — the power-button behaviour in particular is documented
  only indirectly.

### Why the percentage was wrong, and what it does now

There is no fuel gauge; the percentage is estimated from the battery voltage. Upstream used
`(mV − 3300) / 800` on every reading. Measured on our unit while charging:

- The terminal voltage swings by **30–55 mV** with the charger's behaviour (it rises while current flows and falls
  back when it pauses). The old formula turned every swing into 4–7 percentage points — a reading of 67 % then 60 %
  a minute later.
- It needs ≥ 4100 mV for 100 %, but this battery + charger settle around **4.06–4.09 V**, so it could never show 100 %.
- During the "full" plateau the displayed value changed **577 times** in 2.5 hours.

`firmware/sticks3/src/vibe_battery.c` now does:

1. **Median of the last 5 readings** (one reading every 15 s) – removes load spikes and charger ripple.
2. **"Charger says full" latch** – on USB power, voltage ≥ 4040 mV and the charge flag flapping at least 4 times in
   the last 6 minutes (the charger keeps topping up) → show **100 %**, until USB is removed or the voltage drops
   below 4000 mV.
3. **Hysteresis** – on USB a change smaller than 2 points is ignored; on battery the value only goes **down**, unless
   it rises by ≥ 10 points (e.g. after a long rest).
4. After plugging / unplugging the display is held for 2 samples, because the voltage steps by tens of mV.
5. The latch needs about 3 minutes of history after a reboot.
6. **Measured voltage → percentage curve** instead of a straight line. From one constant-load discharge of our unit
   (remaining run time until 3300 mV) the straight line showed e.g. 25 % at 3500 mV when only ≈ 17 % was left,
   and 12 % at 3400 mV when ≈ 3 % was left; near the top it was too low. The table in `vibe_battery.c` replaces it.
7. **USB offset:** with USB power the terminal voltage is ≈ 40 mV above the resting voltage (seen on every
   plug/unplug in the log), so 40 mV is subtracted before the lookup. Without it, a flat battery that had just been
   plugged in showed 33 % after half an hour when it was nearer 20 %.

The curve comes from **one** discharge at one load on **one** unit, and the 40 mV offset is a single-point estimate
(the real offset depends on the charge current). Treat both as a first approximation and keep the log running.

Replaying our own 1058-sample charge log through the same C code: display changes 787 → 25, plateau changes
577 → 2, and the latch engages at 4052 mV (the plateau really started at 11:53, the latch at 11:56). You can repeat
that without hardware, see below.

"100 %" therefore means *the charger considers the battery full*, like on a phone — not that the cell holds its
original rated capacity. The thresholds (4040 / 4000 mV, 4 flips) were tuned on **one** battery and may need
re-tuning on another.

### Telemetry and tools

Every 15 s the device records a raw sample and uploads batches to the bridge (`POST /battery`, protected by the
bridge token). If the bridge is unreachable they wait in a 160-entry ring buffer (about 40 minutes) and are sent
later; every sample carries its own age, so the device needs no real-time clock.

The bridge appends them to `battery_log.csv` (in the bridge's app-data folder; override with
`VIBE_STICK_BATTERY_LOG`; rotates at 10 MB).

| Column | Meaning |
|---|---|
| `bat_mv` | Raw battery terminal voltage |
| `vin_mv` | USB input voltage (≈ 4600–5400 when plugged in, 0 when not) |
| `charging`, `usb` | Charge flag, USB present |
| `pct_shown` | What the screen showed |
| `screen_on`, `recording` | Screen / recording state |
| `audio_idle_s` | Seconds since the speaker or mic last ran (to tell load dips from real ones) |

- `python bridge/tools/battery_report.py [--hours 12]` – splits the log by power state, reports slopes, lists voltage
  steps with a likely cause and prints heuristics. The verdict is a hint, **not a battery health test**; a real
  capacity test needs a controlled full discharge.
- `firmware/sticks3/tools/host_battery_test.c` – builds the same `vibe_battery.c` on a PC, runs six synthetic
  scenarios and can replay a CSV: `cl /I..\include host_battery_test.c ..\src\vibe_battery.c` (or `cc`), then
  `host_battery_test.exe battery_log.csv`.

## 4. Sounds

| Sound | When | What |
|---|---|---|
| **Ready cue** (new) | Hold the blue button, **before the microphone opens** | 100 ms silence, 880 Hz 70 ms, gap, 1320 Hz 100 ms |
| Done | Task finished | Built-in two-tone beep (880 / 1320 Hz). **Optional custom clip**, see below |
| Error / recording failed | | 240 Hz ×3 (upstream) |
| Approval needed | | 600 → 800 Hz (upstream) |

- The ready cue is played *before* the microphone starts, so it is never recorded. Speak after it ends, with a
  half-second pause: the first ~130 ms of the recording are discarded anyway ([section 5](#5-voice-input)).
- The speaker amplifier swallows roughly the first 100 ms after it is switched on; that is why the cue is preceded
  by silence (a bare 45 ms tick was inaudible). 1900 Hz at low level was inaudible too; 880 / 1320 Hz are clear.
- The StickS3 page recommends keeping speaker volume ≤ 75 % on battery to avoid brown-out resets.

### Custom "done" sound

This fork's author uses a custom clip. **No audio file is shipped**: its source and licence are not known to us, and
the safe default is the built-in beep. To use your own sound:

```
python firmware/sticks3/tools/make_done_sound.py my_sound.wav      # 16-bit PCM WAV, any rate / channels
```

This writes `firmware/sticks3/src/vibe_done_sound.h` (git-ignored) – 16 kHz mono, silence trimmed, peak-normalised
(max 3 s). If the file exists at build time the firmware plays it at 0.55× volume (`VIBE_DONE_SOUND_GAIN` in
`vibe_audio.c`); otherwise it falls back to the beep. Only use audio you are allowed to use.

## 5. Voice input

Timeline of one utterance:

```
hold ─300 ms─▶ ready cue ─▶ mic opens (~55 ms) ─▶ you speak ─▶ release
   ─▶ S3 uploads PCM ─▶ bridge: [trim 130 ms] ─▶ recognise ─▶ paste into the focused window
```

- **Hold threshold 450 → 300 ms** and the ready cue: upstream opened the microphone only after 450 ms, so a user
  who started speaking right away lost the first syllable or two. Now the cue tells you when recording is certain.
  On our unit the microphone opens about 55 ms after the cue ends.
- **First 130 ms are cut** (`VIBE_STICK_TRIM_START_MS`). When the codec's ADC powers up it produces a DC step that,
  at the configured 36 dB input gain, clips to full scale and decays over ~130 ms (seen in every one of 51 recordings,
  including ones made before the cue existed, so it is not the cue leaking in). It contains no speech.
- **Prefetch** (`VIBE_STICK_PREFETCH_ASR`, on by default): recognition starts as soon as the audio file arrives,
  in parallel with the device's stop request, instead of after it.
- **Local, offline recognition** (optional): SenseVoice through [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx).
  Set `VIBE_STICK_LOCAL_ASR=sensevoice` and `VIBE_STICK_LOCAL_ASR_MODEL_DIR` to a folder with `model.int8.onnx` and
  `tokens.txt`. Install the extras with `pip install "./bridge[local-asr]"`. Any local failure (missing package or
  model, decode error) falls back to the configured cloud ASR, so a broken model never silences voice input. No audio
  leaves the PC while the local path works. We do not redistribute the model; download it from the sherpa-onnx
  releases (`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2`, ≈ 1 GB, use only the int8 model ≈ 230 MB and
  `tokens.txt`) and check its licence. Model load takes 2–5 s when the bridge starts and about 340 MB of RAM.
- A `timing …` line per recording is written to the bridge log (upload, save, recognition, paste).

Measured on the real device against the real bridge (the log's `timing` lines). "Audio arrives → pasted" is counted
from the moment the bridge receives the upload request, so it includes receiving the PCM over Wi-Fi:

| | Before | After |
|---|---|---|
| Recognition | cloud 0.5–1 s, one cold request took 8.9 s | local 0.15–0.75 s (≈ 0.35 s for a 5 s clip), steady |
| Bridge's answer to the audio upload and to the stop request | 1.4–2.7 s each (two PowerShell processes per request) | ≈ 0.04 s ([section 7](#7-bridge-fixes-and-performance)) |
| Whole paste step | ≈ 350 ms | ≈ 106 ms (clipboard write ≈ 310 ms → ≈ 1 ms; the rest is a deliberate 100 ms wait after Ctrl+V) |
| Audio arrives → pasted | ≈ 3.0 s for a 5 s clip (cloud) | 0.55 s (2.8 s clip), 1.1 s (6–8 s), 1.9 s (11 s), 2.4 s (20 s) |

The cloud ASR keeps working as the fallback. Local and cloud text agreed on our five test sentences except for a
character or two (SenseVoice in both cases), so we did not see a quality loss — five sentences is not a benchmark.

## 6. Claude usage: freshness and self-healing login

The Claude 5H / 7D numbers come from an **undocumented** Anthropic endpoint, called with the OAuth token that Claude
Code stores in `~/.claude/.credentials.json`. Two facts we measured:

- That access token lives **about 8 hours**, and only the **Claude Code CLI** renews it. The desktop app uses its
  own login and never touches that file. So the numbers silently went stale after 8 h.
- Anthropic may change or remove the endpoint at any time.

What the fork does:

1. **Shows the age of the data** ([section 2](#updated-n-ago-line)) so stale numbers are visible instead of
   believable.
2. **Renews the login on its own.** When the stored token has expired the bridge runs, in the background and at most
   once per 20 minutes:

   ```
   claude -p "reply with: ok" --model haiku --no-session-persistence --setting-sources project --tools ""
   ```

   so the CLI renews *its own* credentials. The bridge never reads or uses the refresh token itself. The call skips
   your hooks (`--setting-sources project`), leaves no session file, and drops `CLAUDE_CODE_OAUTH_TOKEN` from its
   environment. Cost: roughly 10 k cached tokens per refresh, about 3 per day. Disable with
   `VIBE_STICK_CLAUDE_TOKEN_REFRESH=off`; point to the executable with `VIBE_STICK_CLAUDE_CLI`.
   Look for `claude login refresh … ok|FAILED` in the log.
3. If it fails (refresh token expired – about every 30 days – or no network), run `claude` once and `/login`.

Unit-tested against a fake CLI, and the real `claude -p …` command was run once by hand from the bridge's Python
(about 7 s, exit code 0, no session file written). The **automatic trigger at a real token expiry has not been
observed yet** — look for the `claude login refresh` log line on your first day.

## 6b. DeepSeek balance page

A third page next to Codex and Claude shows your DeepSeek account balance — nothing else: the logo, `DeepSeek`, the
currency (`CNY`) in small grey type and the remaining amount in big type. Switch with a double click on the right button.

- **Data:** the bridge calls `GET https://api.deepseek.com/user/balance` with your key every 5 minutes (retry after 60 s on a failure;
  the blue button's double click also refreshes it, at most every 30 s). The call runs in a background thread, so a slow
  network never delays the other pages. The key is read from `VIBE_STICK_DEEPSEEK_API_KEY` in `.env` and is only ever sent
  to `api.deepseek.com`. (The bridge also passes the paid and granted parts to the device; the page does not show them.)
- **Low balance:** below **10 CNY** the amount and the small dot next to the name turn **red** (also when DeepSeek reports the
  account as unavailable). The threshold is `DEEPSEEK_LOW_BALANCE_CNY` in `main.c` (CNY balances only).
- **Failures:** a failed refresh keeps showing the last good amount (the `Upd …` line at the bottom grows and turns amber/red).
  With no amount yet the caption says `no API key` or the reason (`bad key`, `offline`, `bad reply`, `http 500`) and the amount is `--`.
- **Fonts:** the device font has no `¥`, so the unit is written as `CNY`. The amount uses Montserrat 32 (20 for very long numbers).
- **Logo:** `firmware/sticks3/assets/providers/deepseek/` holds the logo supplied by the repository owner
  (`logo-source.svg`, `logo-whale.svg/.png`); `tools/make_deepseek_icon.py` turns it into the two device icons. It is DeepSeek's
  trademark artwork — make sure you may redistribute it before publishing your own copy, or replace it.
- The idea and the shape of the API answer come from the open-source
  [DeepSeek-DeskBand](https://github.com/leidichen/DeepSeek-DeskBand) taskbar widget (MIT); no code was copied.
  This page never plays alert sounds.

## 7. Bridge fixes and performance

- **Intermittent "task finished" alert.** The finished-turn alert required the `end_turn` record to be the newest
  record across *all* sessions. Claude Code writes `system/stop_hook_summary` ~2 s *after* a turn when a Stop hook
  exists, and other open sessions also write records, so the alert was often swallowed. Now bookkeeping `system`
  records are ignored (but `system` records that carry an error / cancellation still count) and "newest" is judged
  **per session**. Regression tests cover both and the cancel case.
- **Idle CPU and latency.** Every state request used to start two PowerShell processes (one per provider) and
  re-parse up to 40 session files of up to 1.5 MB each. Now one shared, background-refreshed process snapshot
  (every 10 s) replaces the PowerShell calls and parsed session files are cached by `(mtime, size)`. Measured:
  idle bridge CPU ≈ 7 % → ≈ 0.9 % of one core, `GET /state` ≈ 270 ms → ≈ 36 ms, a Claude observation
  ≈ 287 ms → ≈ 10 ms when nothing changed.
- **Paste** writes the clipboard through the Win32 API (≈ 1 ms) instead of spawning PowerShell (≈ 310 ms), with
  PowerShell kept as a fallback.
- **Quota age**: `provider.quota_age_s` in `/state`; a real fetch timestamp is stored with the quota snapshot.
- **Battery telemetry** endpoint (`POST /battery`, token-protected).

## 8. New configuration

All optional; see `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `VIBE_STICK_LOCAL_ASR` | off | `sensevoice` enables local recognition |
| `VIBE_STICK_LOCAL_ASR_MODEL_DIR` | – | Folder with `model.int8.onnx` and `tokens.txt` |
| `VIBE_STICK_LOCAL_ASR_THREADS` | 8 | CPU threads (1–16) |
| `VIBE_STICK_PREFETCH_ASR` | on | Start recognition when the audio arrives |
| `VIBE_STICK_TRIM_START_MS` | 130 | Cut this much from the start of each device recording; 0 = off |
| `VIBE_STICK_CLAUDE_TOKEN_REFRESH` | on | Renew the Claude Code login when it expired |
| `VIBE_STICK_CLAUDE_CLI` | `claude` on PATH | Path to the Claude Code executable |
| `VIBE_STICK_BATTERY_LOG` | app data folder | CSV for battery telemetry |
| `VIBE_STICK_DEEPSEEK_API_KEY` | – | Enables the DeepSeek balance page (see §6b) |

Config precedence (unchanged from upstream): the bridge reads `<app data>/VibeStick/.env` **first**, then `./.env`;
the first definition of a variable wins. A stale copy in the app-data folder will override the one you are editing.

## 9. Build, flash, test

- Step-by-step for Windows: [WINDOWS_QUICKSTART.md](WINDOWS_QUICKSTART.md).
- Wi-Fi name / password, bridge address and token are **compiled into the firmware** (`vibe_stick_secrets.h`), so a
  pre-built binary cannot be shared — everyone builds their own. Changing any of them means re-flashing.
- Flashing needs a USB-C **data** cable. There is no over-the-air update (single-app partition table).
- Tests: `PYTHONPATH=bridge/src python -m unittest discover -s tests` (what CI runs). Two tests compile C code and
  are skipped when no `cc`/`gcc`/`clang` is on `PATH`.

## 10. Known limitations

- **Tiny battery** (see above). With Wi-Fi connected the device is a desk companion.
- **The device only finds the PC on the same LAN.** If the PC's IP changes the device stays offline until you search
  again with a long press on the right button (give the PC a fixed IP / DHCP reservation).
- **A sleeping PC means a disconnected device.** The device then keeps retrying Wi-Fi/HTTP, which probably drains the
  battery faster (not measured).
- **Security.** The bridge token travels as a plain HTTP header and is broadcast over UDP when you search for
  computers; whoever has it can make the PC press Enter or paste dictated text. `GET /state` needs no token and
  exposes computer name and quota. Write endpoints do require the token. Wi-Fi password and token are readable from
  the device by anyone who plugs it in. Use on a trusted LAN only and scope firewall rules to your subnet.
- Battery thresholds are tuned on one battery.
- Claude usage depends on an undocumented endpoint and may stop working.
- The bridge's background mode on Windows is upstream's `install_windows.ps1` (hidden scheduled tasks). On the
  author's machine those tasks would not start (error `0x80070002`), and a hand-written tray launcher was used
  instead; whether that affects other machines is unknown.

## Credits

Upstream VibeStick © Gary Zhang (MIT). Windows bridge by the 280342193/VibeStick-1 contributors. See `LICENSE` and
`NOTICE`.
