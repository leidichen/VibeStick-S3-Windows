/* Host-side check of src/vibe_battery.c.
 *   cl /nologo /W4 /I..\include host_battery_test.c ..\src\vibe_battery.c
 *   host_battery_test.exe battery_log.csv         (replay a recorded log)
 *   host_battery_test.exe                         (synthetic scenarios only)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "vibe_battery.h"

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

static void scenarios(void)
{
    printf("== synthetic scenarios\n");
    vibe_battery_t b;

    /* 1 single-sample voltage sag on battery power must not change the display */
    vibe_battery_init(&b);
    int shown = 0;
    for (int i = 0; i < 10; ++i) {
        shown = vibe_battery_update(&b, 3900, false, false);
    }
    const int before = shown;
    shown = vibe_battery_update(&b, 3750, false, false); /* speaker pulse */
    CHECK(shown == before, "sag leaked into display: %d -> %d", before, shown);
    for (int i = 0; i < 4; ++i) {
        shown = vibe_battery_update(&b, 3900, false, false);
    }
    CHECK(shown == before, "display did not stay put after the sag: %d vs %d", shown, before);

    /* 2 on battery the display never goes up from small noise, but follows a real drain */
    vibe_battery_init(&b);
    for (int i = 0; i < 6; ++i) {
        vibe_battery_update(&b, 3900, false, false);
    }
    int hi = vibe_battery_update(&b, 3920, false, false);
    CHECK(hi <= vibe_battery_percent_from_mv(3900), "rose on noise: %d", hi);
    int last = hi;
    for (int mv = 3900; mv >= 3600; mv -= 20) {
        for (int k = 0; k < 6; ++k) {
            last = vibe_battery_update(&b, mv, false, false);
        }
    }
    CHECK(last <= vibe_battery_percent_from_mv(3620) + 1, "did not follow the drain: %d", last);

    /* 3 charger flapping on a plateau latches 100 %, and un-plugging releases it */
    vibe_battery_init(&b);
    int pct = 0;
    int latched_at = -1;
    for (int i = 0; i < 80; ++i) {
        const bool chg = (i / 2) % 2 == 0;
        const int mv = chg ? 4090 : 4058;
        pct = vibe_battery_update(&b, mv, chg, true);
        if (latched_at < 0 && vibe_battery_is_full(&b)) {
            latched_at = i;
        }
    }
    CHECK(vibe_battery_is_full(&b) && pct == 100, "not full on the plateau: pct=%d", pct);
    CHECK(latched_at >= 11 && latched_at <= 30, "latched at sample %d (expected 12..30)", latched_at);
    int after = 0;
    for (int i = 0; i < 6; ++i) {
        after = vibe_battery_update(&b, 4070, false, false);
    }
    CHECK(!vibe_battery_is_full(&b), "latch survived unplugging");
    CHECK(after >= 90 && after <= 97, "after unplug shows %d (expected ~96 for 4070 mV)", after);

    /* 4 a steady climb while the charge flag stays on must NOT show 100 % early */
    vibe_battery_init(&b);
    int maxp = 0;
    for (int i = 0; i < 200; ++i) {
        const int mv = 3800 + i; /* 3800..3999 */
        const int p = vibe_battery_update(&b, mv, true, true);
        if (p > maxp) {
            maxp = p;
        }
    }
    CHECK(!vibe_battery_is_full(&b) && maxp < 100, "climb latched too early (max %d)", maxp);

    /* 5 PC-port case: USB present, battery low, charge flag off -> never "full" */
    vibe_battery_init(&b);
    for (int i = 0; i < 60; ++i) {
        vibe_battery_update(&b, 3800, false, true);
    }
    CHECK(!vibe_battery_is_full(&b), "latched on a non-charging low battery");

    /* 6 a lone voltage reading below the latch threshold releases a latched value */
    vibe_battery_init(&b);
    for (int i = 0; i < 80; ++i) {
        const bool chg = (i / 2) % 2 == 0;
        vibe_battery_update(&b, chg ? 4090 : 4058, chg, true);
    }
    for (int i = 0; i < 8; ++i) {
        vibe_battery_update(&b, 3950, false, true);
    }
    CHECK(!vibe_battery_is_full(&b), "latch did not release below 4000 mV");
    printf("   %s\n", g_fail ? "some scenarios failed" : "all scenarios passed");
}

static void replay(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) {
        printf("cannot open %s\n", path);
        g_fail++;
        return;
    }
    char line[512];
    (void)fgets(line, sizeof(line), f); /* header */
    vibe_battery_t b;
    vibe_battery_init(&b);

    long n = 0, old_changes = 0, new_changes = 0, first_full = -1, t_first = 0;
    int prev_old = -1, prev_new = -1, old_min = 101, old_max = -1, new_min = 101, new_max = -1;
    long plat_n = 0, plat_old_changes = 0, plat_new_changes = 0;
    int plat_prev_old = -1, plat_prev_new = -1;
    int plat_new_min = 101, plat_new_max = -1, plat_old_min = 101, plat_old_max = -1;
    long t_prev = 0;
    printf("\n== replay of %s\n   %-9s %-7s %-4s %-4s %-9s %-9s\n", path, "time", "mV", "chg", "usb", "old %", "new %");
    long next_print = 0;
    while (fgets(line, sizeof(line), f)) {
        char tstr[64];
        long epoch;
        int bat, vin, chg, usb, pct, scr, rec, aud;
        if (sscanf(line, "%63[^,],%ld,%d,%d,%d,%d,%d,%d,%d,%d", tstr, &epoch, &bat, &vin, &chg, &usb, &pct, &scr, &rec, &aud) != 10) {
            continue;
        }
        if (t_prev && epoch - t_prev > 120) { /* long hole in the log: a fresh window */
            b.mv_count = 0;
            b.flag_count = 0;
        }
        t_prev = epoch;
        const int old_pct = vibe_battery_percent_from_mv(bat);
        const int new_pct = vibe_battery_update(&b, bat, chg != 0, usb != 0);
        n++;
        if (prev_old >= 0 && old_pct != prev_old) old_changes++;
        if (prev_new >= 0 && new_pct != prev_new) new_changes++;
        prev_old = old_pct;
        prev_new = new_pct;
        if (old_pct < old_min) old_min = old_pct;
        if (old_pct > old_max) old_max = old_pct;
        if (new_pct < new_min) new_min = new_pct;
        if (new_pct > new_max) new_max = new_pct;
        if (!t_first) t_first = epoch;
        if (first_full < 0 && vibe_battery_is_full(&b)) {
            first_full = epoch;
            printf("   --> full latched at %s (%ld min after the log started), %d mV\n", tstr + 11, (epoch - t_first) / 60, bat);
        }
        if (bat >= 4040 && usb) { /* the plateau as defined in the analysis */
            plat_n++;
            if (plat_prev_old >= 0 && old_pct != plat_prev_old) plat_old_changes++;
            if (plat_prev_new >= 0 && new_pct != plat_prev_new) plat_new_changes++;
            plat_prev_old = old_pct;
            plat_prev_new = new_pct;
            if (old_pct < plat_old_min) plat_old_min = old_pct;
            if (old_pct > plat_old_max) plat_old_max = old_pct;
            if (new_pct < plat_new_min) plat_new_min = new_pct;
            if (new_pct > plat_new_max) plat_new_max = new_pct;
        }
        if (epoch >= next_print) {
            printf("   %-9s %-7d %-4d %-4d %-9d %-9d%s\n", tstr + 11, bat, chg, usb, old_pct, new_pct, vibe_battery_is_full(&b) ? "  [full]" : "");
            next_print = epoch + 15 * 60;
        }
    }
    fclose(f);
    printf("\n   samples: %ld\n", n);
    printf("   whole log   : old display %d..%d%% changed %ld times | new display %d..%d%% changed %ld times\n",
           old_min, old_max, old_changes, new_min, new_max, new_changes);
    printf("   charge plateau (>=4040 mV on USB, %ld samples): old %d..%d%% (%ld changes) | new %d..%d%% (%ld changes)\n",
           plat_n, plat_old_min, plat_old_max, plat_old_changes, plat_new_min, plat_new_max, plat_new_changes);
    CHECK(plat_n == 0 || plat_new_changes < plat_old_changes / 4 + 1, "plateau display not calm enough");
}

int main(int argc, char **argv)
{
    scenarios();
    if (argc > 1) {
        replay(argv[1]);
    }
    printf("\n%s (%d failure%s)\n", g_fail ? "RESULT: FAIL" : "RESULT: PASS", g_fail, g_fail == 1 ? "" : "s");
    return g_fail ? 1 : 0;
}
