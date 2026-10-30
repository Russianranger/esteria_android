package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;

/** JNI process ownership only. Runtime selection belongs to ProotProcess. */
final class NativeProcessBridge implements OwnedProcess.Backend {
    NativeProcessBridge() throws IOException {
        try { System.loadLibrary("esteria_process"); }
        catch (UnsatisfiedLinkError error) { throw new IOException("This APK has no native process owner",error); }
    }
    @Override public long start(OwnedProcess.Specification spec) throws IOException {
        String[] environment=spec.environment.entrySet().stream().map(item->item.getKey()+"="+item.getValue()).toArray(String[]::new);
        return startNative(spec.executable.toString(),spec.arguments.toArray(new String[0]),environment,
            spec.cwd.toString(),spec.stdout.toString(),spec.stderr.toString());
    }
    private static native long startNative(String executable,String[] arguments,String[] environment,String cwd,String stdout,String stderr) throws IOException;
    @Override public native int waitFor(long handle,long timeoutMillis) throws IOException;
    @Override public native int terminate(long handle) throws IOException;
    @Override public native long[] diagnostics(long handle) throws IOException;
}
