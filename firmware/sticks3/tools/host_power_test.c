/* Host-side check of src/vibe_power.c.
 *   cc -std=c11 -I../include host_power_test.c ../src/vibe_power.c
 */
#include <stdio.h>

#include "vibe_power.h"

static int g_fail;
#define CHECK(cond, ...)                                  \
    do {                                                  \
        if (!(cond)) {                                    \
            g_fail++;                                     \
            printf("  FAIL: ");                           \
            printf(__VA_ARGS__);                          \
            printf("\n");                                 \
        }                                                 \
    } while (0)

int main(void)
{
    vibe_power_t p;

    /* eco only without USB, with the screen off and not recording */
    CHECK(vibe_power_is_eco(false, false, false), "battery + screen off must be eco");
    CHECK(!vibe_power_is_eco(true, false, false), "USB power is never eco");
    CHECK(!vibe_power_is_eco(false, true, false), "screen on is never eco");
    CHECK(!vibe_power_is_eco(false, false, true), "recording is never eco");
    CHECK(vibe_power_state_poll_ms(true) > vibe_power_state_poll_ms(false), "eco must poll less often");
    CHECK(vibe_power_battery_poll_ms(true) > vibe_power_battery_poll_ms(false), "eco must sample less often");

    /* idle power-off after VIBE_POWER_AUTO_OFF_MS of uninterrupted eco */
    vibe_power_init(&p);
    CHECK(vibe_power_tick(&p, 1000, true) == VIBE_POWER_NONE, "first eco tick only starts the timer");
    CHECK(vibe_power_tick(&p, 1000 + VIBE_POWER_AUTO_OFF_MS - 1, true) == VIBE_POWER_NONE, "too early");
    CHECK(vibe_power_tick(&p, 1000 + VIBE_POWER_AUTO_OFF_MS, true) == VIBE_POWER_OFF_IDLE, "must power off");

    /* any interruption (screen on, USB) restarts the countdown */
    vibe_power_init(&p);
    (void)vibe_power_tick(&p, 0, true);
    (void)vibe_power_tick(&p, VIBE_POWER_AUTO_OFF_MS - 100, false);
    CHECK(vibe_power_tick(&p, VIBE_POWER_AUTO_OFF_MS + 100, true) == VIBE_POWER_NONE, "countdown must restart");
    CHECK(vibe_power_tick(&p, 2 * VIBE_POWER_AUTO_OFF_MS, true) == VIBE_POWER_NONE, "restarted countdown not over yet");
    CHECK(vibe_power_tick(&p, 2 * VIBE_POWER_AUTO_OFF_MS + 200, true) == VIBE_POWER_OFF_IDLE, "restarted countdown over");

    /* warnings: once at 10 %, once at 5 %, nothing in between */
    vibe_power_init(&p);
    CHECK(vibe_power_on_battery_sample(&p, 40, false) == VIBE_POWER_NONE, "40 %% is fine");
    CHECK(vibe_power_on_battery_sample(&p, 10, false) == VIBE_POWER_WARN_LOW, "10 %% warns");
    CHECK(vibe_power_on_battery_sample(&p, 9, false) == VIBE_POWER_NONE, "no repeat warning");
    CHECK(vibe_power_on_battery_sample(&p, 5, false) == VIBE_POWER_WARN_LOW, "5 %% warns again");
    CHECK(vibe_power_on_battery_sample(&p, 4, false) == VIBE_POWER_NONE, "no repeat at 4 %%");

    /* jumping straight below 5 % gives one warning, not two */
    vibe_power_init(&p);
    CHECK(vibe_power_on_battery_sample(&p, 4, false) == VIBE_POWER_WARN_LOW, "one warning");
    CHECK(vibe_power_on_battery_sample(&p, 4, false) == VIBE_POWER_NONE, "and only one");

    /* shutdown needs two consecutive low samples; a single dip is ignored */
    vibe_power_init(&p);
    (void)vibe_power_on_battery_sample(&p, 2, false);
    CHECK(vibe_power_on_battery_sample(&p, 2, false) == VIBE_POWER_OFF_LOW, "two low samples power off");
    vibe_power_init(&p);
    (void)vibe_power_on_battery_sample(&p, 2, false);
    (void)vibe_power_on_battery_sample(&p, 8, false);
    CHECK(vibe_power_on_battery_sample(&p, 2, false) != VIBE_POWER_OFF_LOW, "a single dip must not power off");

    /* USB power never shuts down and rearms the warnings */
    vibe_power_init(&p);
    (void)vibe_power_on_battery_sample(&p, 8, false);
    CHECK(vibe_power_on_battery_sample(&p, 1, true) == VIBE_POWER_NONE, "USB: no action even at 1 %%");
    CHECK(vibe_power_on_battery_sample(&p, 1, true) == VIBE_POWER_NONE, "USB: still none");
    CHECK(vibe_power_on_battery_sample(&p, 9, false) == VIBE_POWER_WARN_LOW, "warning rearmed after USB");

    printf(g_fail ? "RESULT: FAIL (%d)\n" : "RESULT: PASS\n", g_fail);
    return g_fail ? 1 : 0;
}
