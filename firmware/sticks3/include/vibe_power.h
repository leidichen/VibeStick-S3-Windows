#pragma once

/* Power policy for battery operation. Pure C, no ESP-IDF dependencies, so it is unit-tested on the PC
 * (tools/host_power_test.c).
 *
 * Why: a logged night on battery with the screen off drained the 250 mAh cell in 6.5 h (about -145 mV/h)
 * because Wi-Fi stayed busy (state poll every 5 s) and nothing ever shut the device down; it ran until the
 * PMIC cut it off at 2.96 V.
 *
 *  - "eco" = no USB power, screen off, not recording. Then poll the bridge rarely and let the radio sleep deeper.
 *  - eco for VIBE_POWER_AUTO_OFF_MS in a row -> power off (the power button turns it on again).
 *  - battery warnings at <= 10 % and <= 5 % (once each per discharge); power off at <= 2 % so the cell is
 *    not run to the PMIC cut-off. Plugging in USB rearms everything.
 */

#include <stdbool.h>
#include <stdint.h>

#define VIBE_POWER_STATE_POLL_MS 5000
#define VIBE_POWER_STATE_POLL_ECO_MS 20000
#define VIBE_POWER_BATTERY_POLL_MS 15000
#define VIBE_POWER_BATTERY_POLL_ECO_MS 60000
#ifndef VIBE_POWER_AUTO_OFF_MS
#define VIBE_POWER_AUTO_OFF_MS (30 * 60 * 1000)
#endif
#define VIBE_POWER_WARN1_PERCENT 10
#define VIBE_POWER_WARN2_PERCENT 5
#define VIBE_POWER_SHUTDOWN_PERCENT 2
#define VIBE_POWER_SHUTDOWN_CONFIRMS 2 /* consecutive samples at or below the shutdown level */

typedef enum {
    VIBE_POWER_NONE = 0,
    VIBE_POWER_WARN_LOW,      /* play a warning, light the screen briefly */
    VIBE_POWER_OFF_IDLE,      /* idle on battery for too long */
    VIBE_POWER_OFF_LOW,       /* battery nearly empty */
} vibe_power_action_t;

typedef struct {
    int64_t eco_since_ms; /* -1 = not in eco */
    bool warned1;
    bool warned2;
    int low_count;
} vibe_power_t;

void vibe_power_init(vibe_power_t *p);

bool vibe_power_is_eco(bool usb_powered, bool display_awake, bool recording);
int vibe_power_state_poll_ms(bool eco);
int vibe_power_battery_poll_ms(bool eco);

/* Call for every filtered battery sample. */
vibe_power_action_t vibe_power_on_battery_sample(vibe_power_t *p, int percent, bool usb_powered);

/* Call often (about every 100 ms) with the current time. */
vibe_power_action_t vibe_power_tick(vibe_power_t *p, int64_t now_ms, bool eco);
