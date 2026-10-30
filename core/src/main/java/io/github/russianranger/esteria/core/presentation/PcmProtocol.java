package io.github.russianranger.esteria.core.presentation;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Playback-only TRASC v1 wire compatibility. No microphone or network service. */
public final class PcmProtocol {
    public static final int MAGIC = 0x50414c54, RATE = 48000, CHANNELS = 2;
    public static final int MAX_WRITE_FRAMES = 4096, MAX_BUFFER_FRAMES = 48000;
    public interface Sink extends AutoCloseable {
        void configure(int capacityFrames) throws IOException;
        void start() throws IOException;
        void stop() throws IOException;
        void reset() throws IOException;
        int playbackHead() throws IOException;
        /** Return bytes accepted, including zero; the producer retries unaccepted frames. */
        int write(byte[] pcm, int bytes) throws IOException;
        @Override void close();
    }
    private long acceptedFrames;
    public long acceptedFrames() { return acceptedFrames; }

    private static int word(DataInputStream input) throws IOException {
        return Integer.reverseBytes(input.readInt());
    }
    private static void reply(DataOutputStream output, int value) throws IOException {
        output.writeInt(Integer.reverseBytes(value));
        output.flush();
    }
    public void run(InputStream source, OutputStream destination, Sink sink) throws IOException {
        DataInputStream input = new DataInputStream(new BufferedInputStream(source, 16384));
        DataOutputStream output = new DataOutputStream(destination);
        try {
            if (word(input) != MAGIC || word(input) != 1 || word(input) != RATE || word(input) != CHANNELS)
                throw new IOException("Unsupported PCM stream");
            int capacity = word(input);
            if (capacity < 64 || capacity > MAX_BUFFER_FRAMES) throw new IOException("Invalid PCM capacity");
            sink.configure(capacity);
            reply(output, 0);
            byte[] pcm = new byte[MAX_WRITE_FRAMES * 4];
            for (;;) {
                // Clean EOF is valid only between commands. Truncated command words fail.
                int first = input.read();
                if (first == -1) return;
                int command = first | input.readUnsignedByte() << 8 | input.readUnsignedByte() << 16 |
                        input.readUnsignedByte() << 24;
                switch (command) {
                    case 1: sink.start(); reply(output, 0); break;
                    case 2: sink.stop(); reply(output, 0); break;
                    case 3: reply(output, sink.playbackHead()); break;
                    case 4:
                        int frames = word(input);
                        if (frames < 1 || frames > MAX_WRITE_FRAMES) throw new IOException("Invalid PCM write");
                        int bytes = frames * 4;
                        input.readFully(pcm, 0, bytes);
                        int written = sink.write(pcm, bytes);
                        if (written < 0 || written > bytes || written % 4 != 0)
                            throw new IOException("PCM sink rejected write");
                        acceptedFrames += written / 4;
                        reply(output, written / 4);
                        break;
                    case 5: sink.reset(); reply(output, 0); break;
                    default: throw new IOException("Unknown PCM command");
                }
            }
        } finally {
            sink.close();
        }
    }
}
