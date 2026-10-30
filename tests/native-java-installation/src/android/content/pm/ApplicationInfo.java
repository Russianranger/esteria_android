package android.content.pm;

/** Compile-time Android API shape only. Context refuses this Android-only lookup
 * in the Linux qualification; the production ARM64 locator is replaced there. */
public final class ApplicationInfo {
    public String nativeLibraryDir;
}
