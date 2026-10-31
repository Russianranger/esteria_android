package io.github.russianranger.esteria;

import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.Map;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** History API/component checks only; no low-memory kill, OOM or Thor failure is simulated as actual evidence. */
@RunWith(AndroidJUnit4.class)
public final class ProcessExitDiagnosticsTest {
    @Test public void actualAndroidHistoryQueryIsBoundedToOwnPackage() {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Map<String, String> facts = ProcessExitDiagnostics.collect(context);
        assertEquals("own-package-android-exit-history-not-current-memory", facts.get("process.exitHistory.scope"));
        assertEquals("false", facts.get("process.exitHistory.traceRead"));
        assertEquals("2", facts.get("process.exitHistory.maxRecords"));
        if (Build.VERSION.SDK_INT >= 30) {
            assertEquals("available", facts.get("process.exitHistory.status"));
            assertEquals(context.getPackageName(), facts.get("process.exitHistory.package"));
            int count = Integer.parseInt(facts.get("process.exitHistory.recordCount"));
            assertTrue(count >= 0 && count <= 2);
            assertTrue("At most two bounded scalar record projections", facts.size() <= 27);
            assertEquals(Boolean.toString(android.app.ActivityManager.isLowMemoryKillReportSupported()),
                    facts.get("process.exitHistory.lowMemoryKillReportingSupported"));
            for (int i = 0; i < count; i++) {
                String prefix = "process.exitHistory." + i + ".";
                assertNotNull(facts.get(prefix + "reason"));
                assertTrue(facts.get(prefix + "description").length() <= 540);
                Long.parseLong(facts.get(prefix + "pssKiB"));
                Long.parseLong(facts.get(prefix + "rssKiB"));
                Integer.parseInt(facts.get(prefix + "importance"));
            }
        } else assertEquals("unsupported-before-api30", facts.get("process.exitHistory.status"));
    }

    @Test public void lowMemoryKillJavaOomAndOtherExitsRemainDistinct() {
        assertEquals("LOW_MEMORY", ProcessExitDiagnostics.reasonName(ApplicationExitInfo.REASON_LOW_MEMORY));
        assertEquals("android-reported-low-memory-kill", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_LOW_MEMORY, ""));
        assertEquals("CRASH", ProcessExitDiagnostics.reasonName(ApplicationExitInfo.REASON_CRASH));
        assertEquals("crash-description-reports-java-oom", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_CRASH,
                "java.lang.OutOfMemoryError: Failed to allocate"));
        assertEquals("not-established-by-exit-record", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_CRASH, "crash"));
        assertEquals("not-established-by-exit-record", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_SIGNALED, "SIGKILL"));
        assertEquals("not-established-by-exit-record", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_CRASH_NATIVE, "memory fault"));
        assertEquals("not-established-by-exit-record", ProcessExitDiagnostics.memoryClassification(ApplicationExitInfo.REASON_USER_REQUESTED, "low memory mentioned by user"));
        assertEquals("UNKNOWN(999)", ProcessExitDiagnostics.reasonName(999));
    }

    @Test public void descriptionsAreBoundedRedactedAndSingleLine() {
        String value = "password=private-fixture-secret\n" + "x".repeat(10000);
        String sanitized = ProcessExitDiagnostics.clean(value, 512);
        assertFalse(sanitized.contains("private-fixture-secret"));
        assertFalse(sanitized.contains("\n"));
        assertTrue(sanitized.length() <= 540);
        assertEquals("one two three", ProcessExitDiagnostics.clean("one\ntwo\u0000three", 512));
        assertEquals("", ProcessExitDiagnostics.clean(null, 512));
    }
}
