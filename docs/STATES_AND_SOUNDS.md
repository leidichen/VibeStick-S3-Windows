# States And Sounds

VibeStick plays sounds for key agent status changes on the home screen, and one short **ready cue** right before
a recording starts.

| State | Trigger | Sound |
| --- | --- | --- |
| Ready cue (fork) | Blue button held long enough, **before** the microphone opens | 100 ms silence, 880 Hz 70 ms, 25 ms gap, 1320 Hz 100 ms |
| Completed / 完成 | Codex or Claude reports `DONE`, `COMPLETED`, or `SUCCESS` | 880 Hz 80 ms, 40 ms gap, 1320 Hz 120 ms (or the optional custom clip, below) |
| Error / 报错 | Codex or Claude reports `ERROR`, `FAILED`, or `FAILURE` | 240 Hz 100 ms, 60 ms gap, repeated 3 times |
| Recording failed / 识别失败 | Recording upload, ASR, transcript rejection, or paste injection fails | 240 Hz 100 ms, 60 ms gap, repeated 3 times |
| Waiting for approval / 等待审批 | Codex or Claude reports `APPROVAL`, `WAITING_APPROVAL`, `PENDING_APPROVAL`, or `NEEDS_APPROVAL` | 600 Hz 100 ms, 60 ms gap, 800 Hz 100 ms |

## No Sound

These states and events do not play sounds:

- Recording in progress (the ready cue plays *before* it).
- Idle.
- Ready.
- Running.
- Thinking.
- Polling.
- Provider switching.
- Quota refresh.
- Quota stale.
- Screen refresh and rotation.
- `/state` polling.

## Implementation

Sound generation lives in `firmware/sticks3/src/vibe_audio.c`.

The firmware generates 16 kHz mono 16-bit PCM in memory and plays it through the ES8311 / I2S speaker path. No WAV, MP3, TTS, or network service is used for agent alert sounds.

The speaker amplifier swallows roughly the first 100 ms after it is switched on, so short cues start with silence.

### Optional custom "done" clip (fork)

If `firmware/sticks3/src/vibe_done_sound.h` exists at build time the firmware plays that clip (at 0.55x volume) for the
*completed* sound instead of the two-tone beep. The file is git-ignored and **no audio is shipped**; create it from your
own WAV with `firmware/sticks3/tools/make_done_sound.py` (see [FORK_CHANGES.md](FORK_CHANGES.md#4-sounds)).

Recording has priority. If recording is active, alert sounds are skipped instead of queued.

Duplicate prevention lives in `firmware/sticks3/src/main.c`. A sound is played only once for a new `alert.event_id`; if no event id exists, the firmware falls back to status-edge detection.
An alert wakes the screen if it was switched off.
