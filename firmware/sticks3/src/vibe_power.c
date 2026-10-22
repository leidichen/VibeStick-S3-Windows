#include "vibe_power.h"

void vibe_power_init(vibe_power_t *p)
{
    p->eco_since_ms = -1;
    p->warned1 = false;
    p->warned2 = false;
    p->low_count = 0;
}

bool vibe_power_is_eco(bool usb_powered, bool display_awake, bool recording)
{
    return !usb_powered && !display_awake && !recording;
}

int vibe_power_state_poll_ms(bool eco)
{
    return eco ? VIBE_POWER_STATE_POLL_ECO_MS : VIBE_POWER_STATE_POLL_MS;
}

int vibe_power_battery_poll_ms(bool eco)
{
    return eco ? VIBE_POWER_BATTERY_POLL_ECO_MS : VIBE_POWER_BATTERY_POLL_MS;
}

vibe_power_action_t vibe_power_on_battery_sample(vibe_power_t *p, int percent, bool usb_powered)
{
    if (usb_powered) {
        p->warned1 = false;
        p->warned2 = false;
        p->low_count = 0;
        return VIBE_POWER_NONE;
    }
    if (percent <= VIBE_POWER_SHUTDOWN_PERCENT) {
        if (++p->low_count >= VIBE_POWER_SHUTDOWN_CONFIRMS) {
            return VIBE_POWER_OFF_LOW;
        }
    } else {
        p->low_count = 0;
    }
    if (percent <= VIBE_POWER_WARN2_PERCENT && !p->warned2) {
        p->warned1 = true;
        p->warned2 = true;
        return VIBE_POWER_WARN_LOW;
    }
    if (percent <= VIBE_POWER_WARN1_PERCENT && !p->warned1) {
        p->warned1 = true;
        return VIBE_POWER_WARN_LOW;
    }
    return VIBE_POWER_NONE;
}

vibe_power_action_t vibe_power_tick(vibe_power_t *p, int64_t now_ms, bool eco)
{
    if (!eco) {
        p->eco_since_ms = -1;
        return VIBE_POWER_NONE;
    }
    if (p->eco_since_ms < 0) {
        p->eco_since_ms = now_ms;
        return VIBE_POWER_NONE;
    }
    if (now_ms - p->eco_since_ms >= VIBE_POWER_AUTO_OFF_MS) {
        return VIBE_POWER_OFF_IDLE;
    }
    return VIBE_POWER_NONE;
}
