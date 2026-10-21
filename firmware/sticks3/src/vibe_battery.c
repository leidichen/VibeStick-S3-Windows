#include "vibe_battery.h"

#include <string.h>

#define FULL_ON_MV 4040  /* the charge plateau of this battery starts here; below it the charger is still working */
#define FULL_OFF_MV 4000 /* hysteresis: the latch only drops below this */
#define FULL_MIN_FLIPS 4
#define FULL_MIN_FLAG_SAMPLES 12 /* at least 3 minutes of history before the latch may engage */
#define SETTLE_SAMPLES 2
#define USB_DEADBAND 2
#define BATTERY_RISE_THRESHOLD 10

void vibe_battery_init(vibe_battery_t *b)
{
    memset(b, 0, sizeof(*b));
}

int vibe_battery_percent_from_mv(int mv)
{
    int level = (mv - 3300) * 100 / (4150 - 3350);
    if (level < 0) {
        return 0;
    }
    if (level > 100) {
        return 100;
    }
    return level;
}

static void push_mv(vibe_battery_t *b, int mv)
{
    if (mv < 0) {
        mv = 0;
    } else if (mv > 65535) {
        mv = 65535;
    }
    b->mv[b->mv_pos] = (uint16_t)mv;
    b->mv_pos = (b->mv_pos + 1) % VIBE_BATT_MEDIAN_N;
    if (b->mv_count < VIBE_BATT_MEDIAN_N) {
        b->mv_count++;
    }
}

static int median_mv(const vibe_battery_t *b)
{
    uint16_t tmp[VIBE_BATT_MEDIAN_N];
    const int n = b->mv_count;
    memcpy(tmp, b->mv, sizeof(tmp));
    /* only the first n slots are valid until the ring wraps; after that all N are */
    for (int i = 1; i < n; ++i) {
        uint16_t v = tmp[i];
        int j = i - 1;
        while (j >= 0 && tmp[j] > v) {
            tmp[j + 1] = tmp[j];
            --j;
        }
        tmp[j + 1] = v;
    }
    return tmp[n / 2];
}

static void push_flag(vibe_battery_t *b, bool charging)
{
    b->flags[b->flag_pos] = charging ? 1 : 0;
    b->flag_pos = (b->flag_pos + 1) % VIBE_BATT_FLAG_WINDOW;
    if (b->flag_count < VIBE_BATT_FLAG_WINDOW) {
        b->flag_count++;
    }
}

static int flag_flips(const vibe_battery_t *b)
{
    int flips = 0;
    const int n = b->flag_count;
    /* oldest entry sits at flag_pos once the ring is full, otherwise at index 0 */
    const int start = (n == VIBE_BATT_FLAG_WINDOW) ? b->flag_pos : 0;
    for (int i = 1; i < n; ++i) {
        const uint8_t prev = b->flags[(start + i - 1) % VIBE_BATT_FLAG_WINDOW];
        const uint8_t cur = b->flags[(start + i) % VIBE_BATT_FLAG_WINDOW];
        if (prev != cur) {
            flips++;
        }
    }
    return flips;
}

int vibe_battery_update(vibe_battery_t *b, int bat_mv, bool charging, bool usb_powered)
{
    /* Power source changed: the terminal voltage steps by tens of mV, so the old window is meaningless. */
    if (b->have_prev_usb && b->prev_usb != usb_powered) {
        b->mv_count = 0;
        b->mv_pos = 0;
        b->flag_count = 0;
        b->flag_pos = 0;
        b->settle_left = SETTLE_SAMPLES;
        if (!usb_powered) {
            b->full_latched = false;
        }
    }
    b->have_prev_usb = true;
    b->prev_usb = usb_powered;

    push_mv(b, bat_mv);
    push_flag(b, charging);
    const int med = median_mv(b);
    const int raw = vibe_battery_percent_from_mv(med);

    if (!usb_powered) {
        b->full_latched = false;
    } else if (b->full_latched) {
        if (med < FULL_OFF_MV) {
            b->full_latched = false;
        }
    } else if (med >= FULL_ON_MV && b->flag_count >= FULL_MIN_FLAG_SAMPLES &&
               flag_flips(b) >= FULL_MIN_FLIPS) {
        b->full_latched = true;
    }

    if (!b->shown_valid) {
        b->shown = b->full_latched ? 100 : raw;
        b->shown_valid = true;
        return b->shown;
    }
    if (b->settle_left > 0) {
        b->settle_left--;
        return b->shown;
    }

    if (usb_powered) {
        const int target = b->full_latched ? 100 : raw;
        const int diff = target > b->shown ? target - b->shown : b->shown - target;
        if (target == 100 || diff >= USB_DEADBAND) {
            b->shown = target;
        }
    } else {
        if (raw < b->shown) {
            b->shown = raw;
        } else if (raw >= b->shown + BATTERY_RISE_THRESHOLD) {
            b->shown = raw;
        }
    }
    return b->shown;
}

bool vibe_battery_is_full(const vibe_battery_t *b)
{
    return b->full_latched;
}
