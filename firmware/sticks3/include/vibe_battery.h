#pragma once

/* Battery percentage shown on the screen. Pure C, no ESP-IDF dependencies, so it can be replayed on a PC
 * against a recorded battery_log.csv (see tools/host_battery_test.c).
 *
 * Why this exists: the raw terminal voltage jumps by 30..55 mV with the charger's behaviour, and the old
 * "(mV - 3300) / 800" conversion turned every jump into 4..7 percentage points. It also needed >= 4100 mV
 * for 100 %, which this battery + charger never reach (they settle around 4.06..4.09 V).
 *
 *  - median of the last 5 readings removes spikes (load pulses, charger ripple)
 *  - "full" latch: on USB power, battery >= 4040 mV and the charge flag flapping (>= 4 changes in the last
 *    6 minutes, i.e. the charger keeps topping up) -> show 100 % until USB is removed or voltage < 4000 mV
 *  - hysteresis: on USB a change smaller than 2 points is ignored; on battery the value only goes down
 *    (a rise of >= 10 points is accepted, e.g. after a long rest)
 */

#include <stdbool.h>
#include <stdint.h>

#define VIBE_BATT_MEDIAN_N 5
#define VIBE_BATT_USB_OFFSET_MV 40 /* terminal voltage rise while USB power is present */
#define VIBE_BATT_FLAG_WINDOW 24 /* samples; one sample per 15 s = 6 minutes */

typedef struct {
    uint16_t mv[VIBE_BATT_MEDIAN_N];
    int mv_count;
    int mv_pos;
    uint8_t flags[VIBE_BATT_FLAG_WINDOW];
    int flag_count;
    int flag_pos;
    bool have_prev_usb;
    bool prev_usb;
    int settle_left; /* samples to wait after a power source change before moving the displayed value */
    bool full_latched;
    bool shown_valid;
    int shown;
} vibe_battery_t;

void vibe_battery_init(vibe_battery_t *b);

/* Resting voltage -> percentage, piecewise-linear over a curve measured on this device (see vibe_battery.c).
 * The old straight line 3300..4100 mV overstated low charge by 7..9 points. */
int vibe_battery_percent_from_mv(int mv);

/* Feed one reading (every ~15 s). Returns the percentage to display. */
int vibe_battery_update(vibe_battery_t *b, int bat_mv, bool charging, bool usb_powered);

bool vibe_battery_is_full(const vibe_battery_t *b);
