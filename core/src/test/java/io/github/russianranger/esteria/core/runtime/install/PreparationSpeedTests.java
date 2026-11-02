package io.github.russianranger.esteria.core.runtime.install;

import java.util.Map;
import java.util.HashMap;
import java.util.concurrent.atomic.AtomicReference;

/** Real JVM scope/environment checks; no device throughput claim. */
public final class PreparationSpeedTests {
    public static void main(String[] arguments) throws Exception {
        check(PreparationSpeed.DEFAULT == PreparationSpeed.BALANCED, "Balanced launcher default");
        check(PreparationSpeed.values().length == 3, "Three bounded speed choices");
        long[] rates = {8L << 20, 32L << 20, 64L << 20};
        Map<String,String> original = new HashMap<>(Map.of("WINEPREFIX", "/work/wine"));
        Map<String,String> expectedOriginal = Map.copyOf(original);
        check(RuntimeReadPolicy.preparationEnvironment(original) == original, "No speed selected outside preparation");
        for (PreparationSpeed speed : PreparationSpeed.values()) {
            check(speed.bytesPerSecond == rates[speed.ordinal()], "Exact fixed rate");
            check(PreparationSpeed.fromId(speed.id) == speed && speed.toString().equals(speed.label), "Stable UI and wire identities");
            try (RuntimeReadPolicy.Scope selected = RuntimeReadPolicy.install((p,o,n) -> {}, speed)) {
                Map<String,String> actual = RuntimeReadPolicy.preparationEnvironment(original);
                check(actual.get(PreparationSpeed.ENVIRONMENT_KEY).equals(speed.id), "Same selection reaches the guest");
                check(actual.get("WINEPREFIX").equals("/work/wine") && original.equals(expectedOriginal), "Caller environment preserved");
                try {actual.put("foreign", "change"); throw new AssertionError("Mutable selected environment");}
                catch (UnsupportedOperationException expected) { }
                try (RuntimeReadPolicy.Scope nested = RuntimeReadPolicy.install((p,o,n) -> {})) {
                    check(RuntimeReadPolicy.preparationEnvironment(original).equals(actual), "Nested read observer retains selection");
                }
                AtomicReference<Throwable> failure = new AtomicReference<>();
                Thread unrelated = new Thread(() -> {
                    try {check(RuntimeReadPolicy.preparationEnvironment(original) == original, "Selection does not leak to another worker");}
                    catch (Throwable error) {failure.set(error);}
                });
                unrelated.start(); unrelated.join();
                if (failure.get() != null) throw new AssertionError(failure.get());
                PreparationSpeed other = speed == PreparationSpeed.FAST ? PreparationSpeed.GENTLE : PreparationSpeed.FAST;
                try (RuntimeReadPolicy.Scope changed = RuntimeReadPolicy.install((p,o,n) -> {}, other)) {
                    Map<String,String> injected = Map.of(PreparationSpeed.ENVIRONMENT_KEY, speed.id);
                    check(RuntimeReadPolicy.preparationEnvironment(injected).get(PreparationSpeed.ENVIRONMENT_KEY).equals(other.id), "Explicit scope owns the environment choice");
                }
                check(RuntimeReadPolicy.preparationEnvironment(original).equals(actual), "Nested selection restores outer choice");
            }
            check(RuntimeReadPolicy.preparationEnvironment(original) == original, "Closed selection does not affect game launches");
        }
        for (String invalid : new String[]{null, "", "FAST", "unlimited", "64", "fast\n"}) {
            try {PreparationSpeed.fromId(invalid); throw new AssertionError("Unknown speed accepted");}
            catch (IllegalArgumentException expected) { }
        }
        System.out.println("PASS: preparation speed rates, nested scopes, worker isolation and sanitized guest environment");
    }
    private static void check(boolean condition, String detail) {
        if (!condition) throw new AssertionError(detail);
    }
}
