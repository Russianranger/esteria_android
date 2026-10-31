package io.github.russianranger.esteria;

/** Advisory release of already-synced import pages; never truncates or changes file bytes. */
final class NativeImportCache {
    private static final boolean AVAILABLE;
    static {
        boolean loaded;
        try { System.loadLibrary("esteria_process"); loaded = true; }
        catch (UnsatisfiedLinkError | SecurityException unavailable) { loaded = false; }
        AVAILABLE = loaded;
    }
    private NativeImportCache() { }
    /** Zero means the kernel accepted the advice, not a guarantee of reclaimed pages. */
    static int drop(int fd, long offset, long length) {
        if (!AVAILABLE) return -1;
        try { return dropNative(fd, offset, length); }
        catch (UnsatisfiedLinkError unavailable) { return -1; }
    }
    private static native int dropNative(int fd, long offset, long length);
}
