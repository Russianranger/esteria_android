package io.github.russianranger.esteria.core.presentation;

import java.util.List;

/** Chooses a display mode for the game window from the session frame cap.
 * A panel refreshing far above the cap still composes and scans out every refresh.
 * This picks the slowest mode at the current resolution that shows each capped frame
 * for a whole number of refreshes. It never raises the refresh rate above the
 * current mode, so a user's lower system setting is kept. Android treats the
 * result as a preference, not a guarantee. */
public final class DisplayRefreshChoice {
    /** Tolerance for vendor rates such as 59.94 or 119.88 Hz. */
    private static final float TOLERANCE_HZ = 0.5f;

    public static final class Mode {
        public final int id, width, height;
        public final float refreshHz;
        public Mode(int id, int width, int height, float refreshHz) {
            this.id = id; this.width = width; this.height = height; this.refreshHz = refreshHz;
        }
    }

    private DisplayRefreshChoice() { }

    /** Returns the preferred mode id, or 0 to leave the system's choice unchanged. */
    public static int preferredModeId(int frameCap, Mode current, List<Mode> supported) {
        if (frameCap <= 0 || current == null || supported == null || !(current.refreshHz > 0)) return 0;
        Mode chosen = null;
        for (Mode mode : supported) {
            if (mode == null || mode.id <= 0 || mode.width != current.width || mode.height != current.height) continue;
            if (!(mode.refreshHz >= frameCap - TOLERANCE_HZ) || mode.refreshHz > current.refreshHz + TOLERANCE_HZ) continue;
            float multiple = Math.round(mode.refreshHz / frameCap) * (float) frameCap;
            if (Math.abs(mode.refreshHz - multiple) > TOLERANCE_HZ) continue;
            if (chosen == null || mode.refreshHz < chosen.refreshHz) chosen = mode;
        }
        return chosen == null ? 0 : chosen.id;
    }
}
