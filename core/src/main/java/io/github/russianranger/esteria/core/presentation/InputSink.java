package io.github.russianranger.esteria.core.presentation;

import java.io.IOException;

/** Physical X11 base-level keysyms and framebuffer coordinates. Text must send
 * explicit Shift/base pairs; unsupported/Unicode mappings fail visibly. */
public interface InputSink {
    /** A whole batch was refused before accepting any event. Retrying is safe;
     * ordinary transport errors and partial individual input are not covered. */
    final class BatchRejected extends IOException {
        private static final long serialVersionUID=1L;
        public BatchRejected(String message){super(message);}
    }
    void key(int keysym, boolean down) throws IOException;
    /** Atomic queue acceptance, not an X11 transaction. At most 256 events. */
    default void keySequence(int[] keysyms, boolean[] down) throws IOException {
        throw new IOException("Atomic key sequences are unsupported by this input sink");
    }
    void pointer(int x, int y, int buttonMask) throws IOException;
    void relativeMotion(int dx, int dy) throws IOException;
    void buttons(int buttonMask) throws IOException;
    void releaseAll() throws IOException;
}
