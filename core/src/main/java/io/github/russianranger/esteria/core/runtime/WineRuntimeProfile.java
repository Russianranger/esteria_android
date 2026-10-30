package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/** Fixed source-owned Wine adaptations selected by the pinned runtime package.
 * This declares launch requirements, not Android or game qualification.
 */
public final class WineRuntimeProfile {
    public static final String PRIVATE_PE_COPY = "WINE_ANDROID_PRIVATE_PE_COPY";
    private final Map<String,String> environment;

    public WineRuntimeProfile(Map<String,?> configured) throws IOException {
        if (configured == null || (!configured.isEmpty() && (configured.size() != 1 ||
                !configured.containsKey(PRIVATE_PE_COPY) || !"1".equals(configured.get(PRIVATE_PE_COPY)))))
            throw new IOException("Unsupported pinned Wine environment profile");
        Map<String,String> selected = new TreeMap<>();
        if (!configured.isEmpty()) selected.put(PRIVATE_PE_COPY, "1");
        environment = Collections.unmodifiableMap(selected);
    }
    public Map<String,String> environment() { return environment; }
    public boolean requiresPrivatePeCopy() { return environment.containsKey(PRIVATE_PE_COPY); }

    /** Session arguments cannot enable, disable or change an unselected adaptation. */
    public Map<String,String> merge(Map<String,String> session) throws IOException {
        if (session == null) throw new IOException("Missing Wine session environment");
        if (session.containsKey(PRIVATE_PE_COPY) && (!environment.containsKey(PRIVATE_PE_COPY) ||
                !environment.get(PRIVATE_PE_COPY).equals(session.get(PRIVATE_PE_COPY))))
            throw new IOException("Wine session conflicts with the pinned runtime profile");
        Map<String,String> merged = new TreeMap<>(session); merged.putAll(environment);
        return Collections.unmodifiableMap(merged);
    }
}
