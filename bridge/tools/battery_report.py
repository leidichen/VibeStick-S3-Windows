#!/usr/bin/env python3
"""Summarise the StickS3 battery log (battery_log.csv) to tell display problems from battery problems.

Usage:  python battery_report.py [path-to-csv] [--hours N]
Default log: %APPDATA%\\VibeStick\\battery_log.csv

The "verdict" lines are heuristics, not measurements of battery health. A real capacity test needs a
full controlled discharge, which this log cannot provide.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

FULL_MV_UI = 4100      # firmware maps 3300..4100 mV linearly to 0..100 %
EMPTY_MV_UI = 3300
STEP_MV = 30           # a jump this large between two neighbouring samples is worth a look
MAX_GAP_S = 90         # samples further apart than this do not count as "neighbouring"


@dataclass
class Row:
    epoch: int
    bat: int
    vin: int
    chg: int
    usb: int
    pct: int
    screen: int
    rec: int
    audio_idle: int

    @property
    def mode(self) -> str:
        if self.usb and self.chg:
            return "charging"
        if self.usb:
            return "usb-not-charging"
        return "battery"


def load(path: Path, hours: float | None) -> list[Row]:
    rows: list[Row] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle):
            try:
                rows.append(Row(int(r["epoch"]), int(r["bat_mv"]), int(r["vin_mv"]), int(r["charging"]),
                                int(r["usb"]), int(r["pct_shown"]), int(r["screen_on"]), int(r["recording"]),
                                int(r["audio_idle_s"])))
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda x: x.epoch)
    if hours:
        cutoff = time.time() - hours * 3600
        rows = [r for r in rows if r.epoch >= cutoff]
    return rows


def fmt_t(epoch: int) -> str:
    return datetime.fromtimestamp(epoch).strftime("%m-%d %H:%M")


def fmt_d(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def slope_mv_per_hour(points: list[Row]) -> float | None:
    if len(points) < 4 or points[-1].epoch - points[0].epoch < 600:
        return None
    xs = [(p.epoch - points[0].epoch) / 3600 for p in points]
    ys = [p.bat for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def segments(rows: list[Row]) -> list[list[Row]]:
    out: list[list[Row]] = []
    for r in rows:
        if out and out[-1][-1].mode == r.mode and r.epoch - out[-1][-1].epoch <= 10 * MAX_GAP_S:
            out[-1].append(r)
        else:
            out.append([r])
    return out


def main() -> int:
    default = Path(os.environ.get("APPDATA", ".")) / "VibeStick" / "battery_log.csv"
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(default))
    ap.add_argument("--hours", type=float, help="only look at the last N hours")
    args = ap.parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"找不到日志: {path}\n(S3 连上 bridge 后约 15 秒开始记录)")
        return 1
    rows = load(path, args.hours)
    if len(rows) < 2:
        print(f"样本太少({len(rows)} 条),多用一会儿再看。")
        return 1

    span = rows[-1].epoch - rows[0].epoch
    print(f"== 数据范围: {fmt_t(rows[0].epoch)} → {fmt_t(rows[-1].epoch)}  ({fmt_d(span)}),{len(rows)} 条样本")
    bats = [r.bat for r in rows]
    print(f"== 电池电压: 最低 {min(bats)} mV,最高 {max(bats)} mV,中位 {int(statistics.median(bats))} mV")
    print(f"== 屏幕显示: 最低 {min(r.pct for r in rows)}%,最高 {max(r.pct for r in rows)}%")
    time_at_100 = sum(1 for r in rows if r.pct >= 100) * 15
    print(f"== 屏幕上显示 100% 的累计时间: {fmt_d(time_at_100)}(需要电压 ≥ {FULL_MV_UI} mV)")

    print("\n== 分段(按 供电状态 切):")
    print(f"   {'起':<12}{'止':<12}{'时长':<8}{'状态':<18}{'电压 起→止 (最低~最高)':<30}{'斜率':<14}{'亮屏占比'}")
    segs = segments(rows)
    summary: dict[str, list[tuple[float, list[Row]]]] = {"charging": [], "usb-not-charging": [], "battery": []}
    for seg in segs:
        dur = seg[-1].epoch - seg[0].epoch
        if dur < 120:
            continue
        sl = slope_mv_per_hour(seg)
        screen_share = 100 * sum(r.screen for r in seg) / len(seg)
        sl_txt = "-" if sl is None else f"{sl:+.0f} mV/h"
        print(f"   {fmt_t(seg[0].epoch):<12}{fmt_t(seg[-1].epoch):<12}{fmt_d(dur):<8}{seg[0].mode:<18}"
              f"{seg[0].bat}→{seg[-1].bat} ({min(r.bat for r in seg)}~{max(r.bat for r in seg)}){'':<6}{sl_txt:<14}{screen_share:.0f}%")
        summary[seg[0].mode].append((dur, seg))

    print(f"\n== 相邻样本电压突变 ≥ {STEP_MV} mV:")
    steps = []
    for a, b in zip(rows, rows[1:]):
        if b.epoch - a.epoch > MAX_GAP_S:
            continue
        delta = b.bat - a.bat
        if abs(delta) < STEP_MV:
            continue
        if a.mode != b.mode:
            cause = f"供电状态变化 {a.mode}→{b.mode}"
        elif a.screen != b.screen:
            cause = "亮灭屏切换"
        elif b.audio_idle <= 20 or b.rec or a.rec:
            cause = "扬声器/录音刚工作过(负载冲击)"
        else:
            cause = "无明显触发 ← 值得关注"
        steps.append((b.epoch, delta, a.bat, b.bat, a.pct, b.pct, cause))
    if not steps:
        print("   无")
    for epoch, delta, a, b, pa, pb, cause in steps[-15:]:
        print(f"   {fmt_t(epoch)}  {a}→{b} mV ({delta:+d}),屏幕 {pa}%→{pb}%  原因: {cause}")
    unexplained = [s for s in steps if "无明显" in s[6]]

    print("\n== 判断(启发式,非电池健康检测):")
    notes: list[str] = []
    ch = [seg for dur, seg in summary["charging"] if dur >= 1800]
    if ch:
        peak = max(max(r.bat for r in seg) for seg in ch)
        longest = max(ch, key=len)
        sl = slope_mv_per_hour(longest[-min(len(longest), 120):])
        notes.append(f"充电中最高电压 {peak} mV。")
        if peak >= 4150:
            notes.append("→ 电池能被充到接近满电(≈4.2V)。屏幕上若没到 100%,是换算公式把 4.10V 就当作 100% 的显示问题,与电池无关。"
                         if max(r.pct for r in rows) < 100 else "→ 电池可充满,显示也到过 100%。")
        elif sl is not None and abs(sl) < 15 and peak < 4050:
            notes.append(f"→ 电压长时间几乎不涨({sl:+.0f} mV/h)且停在 {peak} mV:"
                         "充电电流很可能被设备自身的耗电抵消了(屏幕常亮 + Wi-Fi)。试试熄屏充电,再看这份报告。")
        else:
            notes.append("→ 电压在涨但没到满电,数据还不够长或充电还没结束。")
    else:
        notes.append("还没有 ≥30 分钟的连续充电记录,无法判断充电行为。")
    nb = [(dur, seg) for dur, seg in summary["battery"] if dur >= 3600]
    if nb:
        dur, seg = max(nb, key=lambda x: x[0])
        sl = slope_mv_per_hour(seg)
        if sl is not None:
            notes.append(f"最长一段电池供电 {fmt_d(dur)},电压斜率 {sl:+.0f} mV/h(亮屏占比 {100*sum(r.screen for r in seg)/len(seg):.0f}%)。")
    if unexplained:
        notes.append(f"有 {len(unexplained)} 次电压突变找不到触发原因,把这几行发给我看。")
    elif steps:
        notes.append("电压突变都能由供电切换/亮灭屏/发声解释,更像是电压随负载与充电状态变化,不是电池坏了。")
    for n in notes:
        print("   " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
