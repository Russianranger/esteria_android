package io.github.russianranger.esteria.runtime;

import java.io.IOException;

/** Test-APK-only observer. Handles bind identity-checked processes via pidfds. */
final class ProbeProcessHandles {
    static { System.loadLibrary("esteria_probe_process"); }
    private ProbeProcessHandles() { }
    static native long watch(int pid,long startTicks,int tracerPid,String executable,String mappedGuest) throws IOException;
    static native boolean exited(long handle,int timeoutMillis) throws IOException;
    static native void kill(long handle) throws IOException;
    static native void close(long handle) throws IOException;
}
