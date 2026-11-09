package io.github.russianranger.esteria.core.presentation;

import io.github.russianranger.esteria.core.presentation.DisplayRefreshChoice.Mode;
import java.util.List;

/** Pure display-mode selection fixtures. No Android display is used. */
public final class DisplayRefreshChoiceTests {
    private static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }

    public static void main(String[] args) {
        Mode hz60 = new Mode(1, 1920, 1080, 60f), hz90 = new Mode(2, 1920, 1080, 90f), hz120 = new Mode(3, 1920, 1080, 120f);
        Mode other60 = new Mode(4, 1280, 720, 60f), hz48 = new Mode(5, 1920, 1080, 48f), ntsc = new Mode(6, 1920, 1080, 59.94f);
        List<Mode> panel = List.of(hz60, hz90, hz120, other60);

        check(DisplayRefreshChoice.preferredModeId(30, hz120, panel) == 1, "30 FPS on a 120 Hz panel uses 60 Hz");
        check(DisplayRefreshChoice.preferredModeId(60, hz120, panel) == 1, "60 FPS uses 60 Hz");
        check(DisplayRefreshChoice.preferredModeId(24, hz120, panel) == 3, "24 FPS keeps an exact 120 Hz multiple");
        check(DisplayRefreshChoice.preferredModeId(24, hz120, List.of(hz60, hz90, hz120, hz48)) == 5, "24 FPS prefers 48 Hz when offered");
        check(DisplayRefreshChoice.preferredModeId(24, hz60, panel) == 0, "Never raise the refresh rate above the current mode");
        check(DisplayRefreshChoice.preferredModeId(30, hz60, panel) == 1, "Pin the current mode when it already fits");
        check(DisplayRefreshChoice.preferredModeId(30, hz120, List.of(ntsc, hz120)) == 6, "Vendor rates within tolerance");
        check(DisplayRefreshChoice.preferredModeId(30, other60, panel) == 4, "Only the current resolution is considered");
        check(DisplayRefreshChoice.preferredModeId(0, hz120, panel) == 0 && DisplayRefreshChoice.preferredModeId(30, null, panel) == 0 &&
            DisplayRefreshChoice.preferredModeId(30, hz120, null) == 0, "Invalid inputs keep the system choice");
        System.out.println("Display refresh choice passed 9 host checks; no Android display was used");
    }
}
