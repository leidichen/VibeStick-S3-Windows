#!/usr/bin/env python3
"""Turn a WAV file into the optional custom "task done" sound for the StickS3 firmware.

    python make_done_sound.py my_sound.wav            # writes ../src/vibe_done_sound.h
    python make_done_sound.py my_sound.wav --max-seconds 2 --out some/other/path.h

The firmware plays 16 kHz / 16-bit / mono audio. This script (standard library only):
  * reads 16-bit PCM WAV (convert anything else first, e.g. `ffmpeg -i in.mp3 out.wav`),
  * mixes to mono, low-pass filters and resamples to 16 kHz,
  * trims leading / trailing silence and caps the length,
  * normalises the peak to ~0.92 of full scale (the firmware then applies its own volume factor),
  * writes src/vibe_done_sound.h, which is git-ignored on purpose: only use audio you have the right to use.

Without that header the firmware falls back to its built-in two-tone beep.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
from pathlib import Path

TARGET_RATE = 16000
SILENCE_THRESHOLD = 0.0018  # ~ -55 dBFS
PEAK = 0.92


def read_wav(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as handle:
        channels, width, rate, frames = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()
        if width != 2 or handle.getcomptype() != "NONE":
            raise SystemExit(f"{path.name}: only 16-bit PCM WAV is supported (got {width * 8}-bit). Convert it first, e.g. with ffmpeg.")
        raw = handle.readframes(frames)
    count = len(raw) // 2
    values = struct.unpack("<" + "h" * count, raw[: count * 2])
    mono = [sum(values[i : i + channels]) / channels / 32768.0 for i in range(0, count - channels + 1, channels)]
    return rate, mono


def lowpass_resample(samples: list[float], rate: int) -> list[float]:
    if rate == TARGET_RATE:
        return samples
    if rate > TARGET_RATE:  # windowed-sinc low-pass below the new Nyquist frequency to avoid aliasing
        cutoff = 0.45 * TARGET_RATE / rate
        taps = 63
        half = taps // 2
        kernel = []
        for n in range(taps):
            x = n - half
            sinc = 2 * cutoff if x == 0 else math.sin(2 * math.pi * cutoff * x) / (math.pi * x)
            window = 0.54 - 0.46 * math.cos(2 * math.pi * n / (taps - 1))
            kernel.append(sinc * window)
        norm = sum(kernel)
        kernel = [k / norm for k in kernel]
        filtered = []
        length = len(samples)
        for i in range(length):
            acc = 0.0
            for n, k in enumerate(kernel):
                j = i + n - half
                if 0 <= j < length:
                    acc += samples[j] * k
            filtered.append(acc)
        samples = filtered
    out_len = int(len(samples) * TARGET_RATE / rate)
    ratio = rate / TARGET_RATE
    out = []
    for i in range(out_len):
        position = i * ratio
        left = int(position)
        frac = position - left
        right = min(left + 1, len(samples) - 1)
        out.append(samples[left] * (1 - frac) + samples[right] * frac)
    return out


def trim_and_limit(samples: list[float], max_seconds: float) -> list[float]:
    start = next((i for i, v in enumerate(samples) if abs(v) > SILENCE_THRESHOLD), None)
    if start is None:
        raise SystemExit("the file is silent")
    end = len(samples) - next(i for i, v in enumerate(reversed(samples)) if abs(v) > SILENCE_THRESHOLD)
    clip = samples[start:end]
    limit = int(max_seconds * TARGET_RATE)
    if len(clip) > limit:
        fade = int(0.03 * TARGET_RATE)
        clip = clip[:limit]
        for i in range(fade):  # short fade-out so the cut does not click
            clip[limit - fade + i] *= 1 - (i + 1) / fade
    return clip


def write_header(path: Path, pcm: list[int], source: str) -> None:
    lines = []
    for i in range(0, len(pcm), 12):
        lines.append("    " + ", ".join(str(v) for v in pcm[i : i + 12]) + ",")
    text = (
        "#pragma once\n#include <stdint.h>\n#include <stddef.h>\n\n"
        f"/* Custom task-done sound: 16 kHz mono 16-bit PCM, generated from \"{source}\" by tools/make_done_sound.py. */\n"
        "static const int16_t VIBE_DONE_SOUND_PCM[] = {\n" + "\n".join(lines) + "\n};\n"
        "#define VIBE_DONE_SOUND_SAMPLES (sizeof(VIBE_DONE_SOUND_PCM) / sizeof(VIBE_DONE_SOUND_PCM[0]))\n"
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    default_out = Path(__file__).resolve().parent.parent / "src" / "vibe_done_sound.h"
    parser = argparse.ArgumentParser(description="Create the optional custom done-sound header from a WAV file.")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--out", type=Path, default=default_out, help=f"output header (default: {default_out})")
    parser.add_argument("--max-seconds", type=float, default=3.0, help="cap the clip length (default 3 s)")
    args = parser.parse_args()

    rate, mono = read_wav(args.wav)
    clip = trim_and_limit(lowpass_resample(mono, rate), args.max_seconds)
    peak = max(abs(v) for v in clip)
    gain = PEAK / peak
    pcm = [max(-32767, min(32767, int(round(v * gain * 32767)))) for v in clip]
    write_header(args.out, pcm, args.wav.name)
    print(f"{args.wav.name}: {rate} Hz -> {TARGET_RATE} Hz, {len(pcm)} samples ({len(pcm) / TARGET_RATE:.2f} s), peak gain x{gain:.2f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
