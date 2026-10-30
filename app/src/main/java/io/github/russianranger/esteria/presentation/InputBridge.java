package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import io.github.russianranger.esteria.core.presentation.InputProtocol;
import io.github.russianranger.esteria.core.presentation.InputSink;
import java.io.DataInputStream;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;
import java.util.HashSet;
import java.util.Set;

/** Bounded asynchronous XTest transport; never blocks the UI on guest socket writes. */
public final class InputBridge implements InputSink, AutoCloseable {
    public interface Events { void failed(String code); }
    private static final int QUEUE_LIMIT = 256;
    private final LocalSocket socket = new LocalSocket();
    private final ArrayDeque<byte[]> pending = new ArrayDeque<>();
    private final Set<Integer> keys = new HashSet<>();
    private final Events events;
    private Thread writer;
    private boolean closed;
    private int buttonMask;

    /** Connect off the UI thread after the owned helper is ready. */
    public static InputBridge connect(Context context, File sessionDirectory, Events events) throws IOException {
        InputBridge bridge = new InputBridge(events);
        try {
            Path directory = BridgePaths.directory(context, sessionDirectory);
            String path = BridgePaths.endpoint(directory, "input.sock", true);
            bridge.socket.connect(new LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM));
            bridge.socket.setSoTimeout(2000);
            if (bridge.socket.getPeerCredentials().getUid() != android.os.Process.myUid())
                throw new IOException("Input peer does not belong to this application");
            byte[] greeting = new byte[InputProtocol.GREETING.length];
            new DataInputStream(bridge.socket.getInputStream()).readFully(greeting);
            if (!Arrays.equals(greeting, InputProtocol.GREETING)) throw new IOException("Unsupported input protocol");
            bridge.writer = new Thread(bridge::write, "esteria-input");
            bridge.writer.setDaemon(true); bridge.writer.start();
            return bridge;
        } catch (IOException | RuntimeException failure) {
            try { bridge.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }
    private InputBridge(Events events) { this.events = events; }
    private synchronized void enqueue(byte[] event) throws IOException {
        if (closed) throw new IOException("Input transport is closed");
        if (pending.size() >= QUEUE_LIMIT) {
            // Closing causes the guest to release all keys/buttons. Never drop a key-up.
            disconnect();
            throw new IOException("Input queue is full; connection closed to release injected state");
        }
        pending.add(event); notifyAll();
    }
    @Override public synchronized void key(int keysym, boolean down) throws IOException {
        byte[] packet = InputProtocol.packet(3, keysym, down ? 1 : 0, 0);
        if (down && !keys.contains(keysym) && keys.size() >= 128) throw new IOException("Too many held keys");
        enqueue(packet);
        if (down) keys.add(keysym); else keys.remove(keysym);
    }
    @Override public synchronized void keySequence(int[] keysyms, boolean[] down) throws IOException {
        if (closed) throw new IOException("Input transport is closed");
        if (keysyms == null || down == null || keysyms.length != down.length || keysyms.length > QUEUE_LIMIT)
            throw new IOException("Invalid atomic input sequence");
        List<byte[]> batch = new ArrayList<>(keysyms.length);
        Set<Integer> held = new HashSet<>(keys);
        for (int i = 0; i < keysyms.length; ++i) {
            batch.add(InputProtocol.packet(3, keysyms[i], down[i] ? 1 : 0, 0));
            if (down[i]) held.add(keysyms[i]); else held.remove(keysyms[i]);
            if (held.size() > 128) throw new IOException("Too many held keys in input sequence");
        }
        // Validation and capacity reservation finish before any event becomes visible to the writer.
        if (pending.size() + batch.size() > QUEUE_LIMIT)
            throw new InputSink.BatchRejected("Input is busy; try again");
        pending.addAll(batch); keys.clear(); keys.addAll(held); notifyAll();
    }
    @Override public synchronized void pointer(int x, int y, int mask) throws IOException {
        enqueue(InputProtocol.packet(0, x, y, mask)); buttonMask = mask;
    }
    @Override public synchronized void relativeMotion(int dx, int dy) throws IOException {
        enqueue(InputProtocol.packet(1, dx, dy, buttonMask));
    }
    @Override public synchronized void buttons(int mask) throws IOException {
        enqueue(InputProtocol.packet(2, 0, 0, mask)); buttonMask = mask;
    }
    @Override public synchronized void releaseAll() throws IOException {
        if (closed) throw new IOException("Input transport is closed");
        // Reserve room atomically; partial neutralization is not reported as success.
        if (pending.size() + keys.size() + 1 > QUEUE_LIMIT) {
            disconnect(); throw new IOException("Input release queue is full; connection closed");
        }
        for (int key : keys) enqueue(InputProtocol.packet(3, key, 0, 0));
        keys.clear(); enqueue(InputProtocol.packet(2, 0, 0, 0)); buttonMask = 0;
    }
    private void write() {
        try {
            OutputStream output = socket.getOutputStream();
            DataInputStream input = new DataInputStream(socket.getInputStream());
            while (true) {
                byte[] event;
                synchronized (this) {
                    while (!closed && pending.isEmpty()) wait();
                    if (closed) return;
                    event = pending.removeFirst();
                }
                output.write(event); output.flush();
                if (input.readInt() != 0) throw new IOException("Guest rejected input event");
            }
        } catch (IOException | RuntimeException error) {
            boolean failed;
            synchronized (this) { failed = !closed; disconnect(); }
            if (failed && events != null) events.failed("input-transport-failed");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); synchronized (this) { disconnect(); }
        }
    }
    private synchronized void disconnect() {
        closed = true; pending.clear(); keys.clear(); buttonMask = 0; notifyAll();
        try { socket.shutdownInput(); socket.shutdownOutput(); socket.close(); }
        catch (IOException ignored) { try { socket.close(); } catch (IOException alsoClosed) { /* Already disconnected. */ } }
    }
    /** Off-UI close; EOF releases held guest state even if a queued release could not be sent. */
    @Override public void close() throws IOException {
        disconnect();
        if (writer != null && writer != Thread.currentThread()) try {
            writer.join(2500);
            if (writer.isAlive()) throw new IOException("Input writer did not stop");
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); throw new IOException("Input shutdown interrupted", error);
        }
    }
}
