package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.file.Path;

/** Test-only access to the real provider hash path used during PRoot admission. */
public final class TurnipAdmissionReadFixture {
    private TurnipAdmissionReadFixture() { }
    public static String hash(Path file,long expected,RuntimeWork.Cancellation cancelled)throws IOException {
        return RuntimeFiles.hashFile(file,expected,cancelled);
    }
}
