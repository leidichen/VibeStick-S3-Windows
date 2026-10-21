# Changelog

## Unreleased (fork)

Firmware (StickS3)
- Right button: click = screen on/off, double click = switch provider, triple click = portrait/landscape, hold = search computers. Blue button swallowed while the screen is off.
- The backlight no longer turns off after 5 s; only the right button switches it off. Alerts and key presses wake it.
- Landscape layout (blue button on the right), remembered across reboots; full-width 5H/7D bars.
- Home screen shows the Claude 5H/7D quota again, with an `Upd 5m ago` line (amber after 10 min, red after 1 h) counted on the device clock.
- Battery percentage: median of 5 readings, "charger says full" latch (100 % on the charge plateau), hysteresis. New pure-C module with a host test that can replay a recorded log.
- Blue button hold threshold 450 -> 300 ms; a two-tone ready cue plays before the microphone opens.
- Optional custom "done" clip (`make_done_sound.py`); the default is the original beep. No audio is shipped.
- Battery telemetry: raw samples every 15 s, batched upload to the bridge, ring buffer while offline.

Bridge
- Local offline speech recognition (SenseVoice through sherpa-onnx, optional extra `local-asr`) with the cloud ASR as automatic fallback.
- Recognition starts as soon as the audio arrives (prefetch); the first 130 ms of every device recording are cut (microphone start-up DC step).
- Fix: the Claude "task finished" alert was intermittently swallowed by bookkeeping `system` records and by activity in other sessions.
- Session files are cached by (mtime, size) and process detection runs in one shared background snapshot: idle CPU ~7 % -> ~0.9 % of a core, `GET /state` ~270 ms -> ~36 ms.
- Windows paste writes the clipboard through the Win32 API instead of spawning PowerShell.
- Claude usage: real fetch timestamp (`provider.quota_age_s`), and a background renewal of the expired Claude Code login through one tiny headless `claude -p` call (`VIBE_STICK_CLAUDE_TOKEN_REFRESH`).
- `POST /battery` (token protected), `battery_log.csv`, `bridge/tools/battery_report.py`.
- Per-recording `timing` log line.

Docs and tests
- New: `docs/FORK_CHANGES.md` (+ zh-CN), `docs/WINDOWS_QUICKSTART.md` (+ zh-CN); outdated statements about the 5-second backlight timeout, provider switching and recording sounds corrected.
- New tests for the alert fix, session cache, battery telemetry, login renewal, local ASR fallback, recording trim and the C battery filter; two existing tests updated for the shared process snapshot or made to skip without a C compiler.

## v0.1.12

- Improve Windows Codex/ChatGPT/Claude detection and preserve recent task status and alert events even when an agent process exits before the next poll.

## v0.1.11

- A single `VIBE_STICK_ASR_API_KEY` now enables the default SiliconFlow ASR provider; the URL, model, and language are filled automatically for background Windows tasks.

## v0.1.10

- Hide Windows PowerShell helper processes so the bridge does not flash a console window during state polling or paste injection.

## v0.1.9

- Run the Windows bridge from `pythonw.exe` as a hidden per-user task, write background logs to `%APPDATA%\VibeStick\bridge.log`, restart it after an unexpected exit, and stop stale manual bridge processes during installation.

## v0.1.8

- Treat cancelled, interrupted, crashed, or unexpectedly stopped agent tasks as errors so the StickS3 plays the error alert sound.
- Reduce idle power use with 80 MHz CPU operation, Wi-Fi modem sleep, 5-second state polling, 30-second battery refreshes, and lower backlight brightness.

## v0.1.7

- Distinguish an unreachable bridge from an online bridge whose local Codex/Claude provider is not running; the StickS3 now shows `待命` for the latter instead of `离线`.

## v0.1.6

- Search picker uses a complete ASCII font and sanitizes discovered computer names so names and host details remain visible on StickS3.
- Firmware treats non-2xx bridge responses as failures instead of accepting error JSON as state.
- Recording start failures are shown on StickS3, and audio stop failures now trigger the configured error alert.
- Windows installer registers a hidden per-user Scheduled Task, starts the bridge immediately, and keeps the command runner as a manual fallback.
- Windows installer also starts a no-console recording overlay that appears only while the StickS3 is recording or transcribing.
- Windows documentation now states that recording uses the StickS3 microphone over Wi-Fi and that the Windows `.env` needs its own ASR configuration.

## v0.1.5

- Stable StickS3 home screen update: dimmer backlight, 5-second idle backlight sleep, 160 MHz CPU default, and a computer-name panel instead of 5H / 7D quota bars.
- Status dot colors now use green for running/done, yellow for approval, and red for errors.
- Recording upload, ASR, transcript rejection, and paste failures now play the error alert sound.
- Added a Windows Wi-Fi bridge runner script. Runtime state, alerts, recording, and paste handling stay on Wi-Fi.
- Bridge state now includes `computer_name`, with `VIBE_STICK_COMPUTER_NAME` as an override.
- Project names are no longer exposed in bridge state or rendered on the StickS3 home screen.
- Added simple LAN computer discovery: the StickS3 broadcasts over Wi-Fi, passes its bridge token, and stores the selected bridge host.

## v0.1.4

Initial public release of VibeStick — a tiny desktop companion for coding agents on M5Stack StickS3.

- Home screen shows Codex and Claude providers with live status (running / idle / done / approval / error / offline) and independent 5-hour / 7-day usage bars.
- Opt-in real Claude Code subscription usage (5H / 7D) via an undocumented Anthropic endpoint using local credentials; disabled by default, and the token / raw responses are never logged.
- Push-to-talk voice input: record on the StickS3, transcribe via any OpenAI-compatible ASR (e.g. SiliconFlow), and paste into the focused app; a local-command / fully-offline path is also supported.
- Alerts (done / approval / error) play from whichever provider raises them, on the StickS3 speaker.
- First-run helpers (`scripts/setup.sh`, `scripts/doctor.sh`), bridge token authentication, and a bilingual README (English + 中文) with clearly-marked physical steps.

Licensed under MIT.
