package io.github.russianranger.esteria;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.os.Build;
import io.github.russianranger.esteria.core.diagnostics.SupportBundle;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded Android exit history, separate from a current-memory snapshot or a proven import failure. */
@android.annotation.SuppressLint("InlinedApi") // Reason IDs are compile-time integers; API calls remain gated below.
final class ProcessExitDiagnostics {
    static final int MAX_RECORDS = 2; // Seven header facts plus ten scalars per record stay within 27 support facts.
    private ProcessExitDiagnostics() { }

    static Map<String, String> collect(Context context) {
        Map<String, String> facts = new LinkedHashMap<>();
        facts.put("process.exitHistory.scope", "own-package-android-exit-history-not-current-memory");
        facts.put("process.exitHistory.maxRecords", Integer.toString(MAX_RECORDS));
        facts.put("process.exitHistory.traceRead", "false");
        facts.put("process.exitHistory.recordCount", "0");
        if (Build.VERSION.SDK_INT < 30) {
            facts.put("process.exitHistory.status", "unsupported-before-api30");
            return facts;
        }
        try {
            Api30.collect(context, facts);
        } catch (RuntimeException unavailable) {
            facts.put("process.exitHistory.status", "unavailable-" + unavailable.getClass().getSimpleName());
        }
        return facts;
    }

    @android.annotation.TargetApi(30)
    private static final class Api30 {
        static void collect(Context context, Map<String, String> facts) {
            ActivityManager manager = context.getSystemService(ActivityManager.class);
            if (manager == null) {
                facts.put("process.exitHistory.status", "activity-manager-unavailable");
                return;
            }
            String packageName = context.getPackageName();
            facts.put("process.exitHistory.package", clean(packageName, 160));
            facts.put("process.exitHistory.lowMemoryKillReportingSupported",
                    Boolean.toString(ActivityManager.isLowMemoryKillReportSupported()));
            // pid=0 selects this package's retained process history. There is no cross-package query or trace read.
            List<ApplicationExitInfo> history = manager.getHistoricalProcessExitReasons(packageName, 0, MAX_RECORDS);
            int bound = history == null ? 0 : Math.min(MAX_RECORDS, history.size()), count = 0;
            for (int i = 0; i < bound; i++) {
                ApplicationExitInfo item = history.get(i);
                if (item == null) continue;
                String prefix = "process.exitHistory." + count++ + ".";
                String description = clean(item.getDescription(), 512);
                facts.put(prefix + "timestampEpochMs", Long.toString(item.getTimestamp()));
                facts.put(prefix + "process", clean(item.getProcessName(), 160));
                facts.put(prefix + "reasonCode", Integer.toString(item.getReason()));
                facts.put(prefix + "reason", reasonName(item.getReason()));
                facts.put(prefix + "memoryClassification", memoryClassification(item.getReason(), description));
                facts.put(prefix + "status", Integer.toString(item.getStatus()));
                facts.put(prefix + "importance", Integer.toString(item.getImportance()));
                // Android reports the last sampled PSS/RSS in KiB. Zero may mean no sample; these are not current values.
                facts.put(prefix + "pssKiB", Long.toString(item.getPss()));
                facts.put(prefix + "rssKiB", Long.toString(item.getRss()));
                facts.put(prefix + "description", description);
            }
            facts.put("process.exitHistory.recordCount", Integer.toString(count));
            facts.put("process.exitHistory.status", "available");
        }
    }

    static String reasonName(int reason) {
        switch (reason) {
            case ApplicationExitInfo.REASON_EXIT_SELF: return "EXIT_SELF";
            case ApplicationExitInfo.REASON_SIGNALED: return "SIGNALED";
            case ApplicationExitInfo.REASON_LOW_MEMORY: return "LOW_MEMORY";
            case ApplicationExitInfo.REASON_CRASH: return "CRASH";
            case ApplicationExitInfo.REASON_CRASH_NATIVE: return "CRASH_NATIVE";
            case ApplicationExitInfo.REASON_ANR: return "ANR";
            case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE: return "INITIALIZATION_FAILURE";
            case ApplicationExitInfo.REASON_PERMISSION_CHANGE: return "PERMISSION_CHANGE";
            case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE: return "EXCESSIVE_RESOURCE_USAGE";
            case ApplicationExitInfo.REASON_USER_REQUESTED: return "USER_REQUESTED";
            case ApplicationExitInfo.REASON_USER_STOPPED: return "USER_STOPPED";
            case ApplicationExitInfo.REASON_DEPENDENCY_DIED: return "DEPENDENCY_DIED";
            case ApplicationExitInfo.REASON_OTHER: return "OTHER";
            case ApplicationExitInfo.REASON_FREEZER: return "FREEZER";
            case ApplicationExitInfo.REASON_PACKAGE_STATE_CHANGE: return "PACKAGE_STATE_CHANGE";
            case ApplicationExitInfo.REASON_PACKAGE_UPDATED: return "PACKAGE_UPDATED";
            default: return "UNKNOWN(" + reason + ")";
        }
    }

    static String memoryClassification(int reason, String description) {
        if (reason == ApplicationExitInfo.REASON_LOW_MEMORY) return "android-reported-low-memory-kill";
        // A crash, signal, large RSS or generic description is insufficient to identify a Java heap OOM.
        if (reason == ApplicationExitInfo.REASON_CRASH && description != null && description.contains("OutOfMemoryError"))
            return "crash-description-reports-java-oom";
        return "not-established-by-exit-record";
    }

    static String clean(String value, int maximum) {
        if (value == null) return "";
        int count = Math.min(value.length(), maximum);
        StringBuilder bounded = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            char character = value.charAt(i);
            bounded.append(character < 32 || character == 127 ? ' ' : character);
        }
        // Limit the input before regex redaction, avoiding an unbounded description/trace copy.
        return SupportBundle.redact(bounded.toString());
    }
}
