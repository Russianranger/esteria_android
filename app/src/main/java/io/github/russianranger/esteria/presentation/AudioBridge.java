package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.system.ErrnoException;
import android.system.Os;
import android.system.StructStat;
import io.github.russianranger.esteria.core.presentation.PcmProtocol;
import java.io.File;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** Private ALSA playback endpoint. Owns its socket, workers, audio focus and tracks. */
public final class AudioBridge implements AutoCloseable {
    public interface Events { void event(String code); }
    private final Events events;
    private final AudioManager manager;
    private final AudioAttributes attributes = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_GAME).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
    private final AudioFocusRequest focus;
    private final LocalSocket bound = new LocalSocket();
    private final Set<Playback> connections = new HashSet<>();
    private final List<Thread> workers = new ArrayList<>();
    private final String path;
    private LocalServerSocket server;
    private Thread acceptor;
    private volatile boolean closed;
    private volatile float volume = 1;
    private long device, inode;
    private boolean ownsPath, focusRequested;

    public static AudioBridge start(Context context, File sessionDirectory, Events events) throws IOException {
        AudioBridge bridge = new AudioBridge(context, sessionDirectory, events);
        try { bridge.listen(); return bridge; }
        catch (IOException | RuntimeException failure) {
            try { bridge.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }
    private AudioBridge(Context context, File directory, Events events) throws IOException {
        this.events = events;
        Path privateDirectory = BridgePaths.directory(context, directory);
        path = BridgePaths.endpoint(privateDirectory, "audio.sock", false);
        manager = (AudioManager)context.getSystemService(Context.AUDIO_SERVICE);
        if (manager == null) throw new IOException("Android audio service is unavailable");
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes)
                .setOnAudioFocusChangeListener(change -> {
                    if (closed) return;
                    volume = change == AudioManager.AUDIOFOCUS_GAIN ? 1 :
                            change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK ? .2f : 0;
                    List<Playback> active;
                    synchronized (connections) { active = new ArrayList<>(connections); }
                    for (Playback playback : active) playback.volume(volume);
                    event(volume == 1 ? "audio-focus-gained" : "audio-focus-reduced");
                }, new Handler(Looper.getMainLooper())).build();
    }
    private void event(String code) { if (events != null) events.event(code); }
    private void listen() throws IOException {
        bound.bind(new LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM));
        try {
            StructStat stat = Os.lstat(path);
            device = stat.st_dev; inode = stat.st_ino; ownsPath = true;
            Os.chmod(path, 0600);
        } catch (ErrnoException error) { throw new IOException("Cannot protect audio endpoint", error); }
        server = new LocalServerSocket(bound.getFileDescriptor());
        focusRequested = true;
        int granted = manager.requestAudioFocus(focus);
        volume = granted == AudioManager.AUDIOFOCUS_REQUEST_GRANTED ? 1 : 0;
        event(volume == 1 ? "audio-focus-gained" : "audio-focus-denied");
        acceptor = new Thread(this::accept, "esteria-audio-accept");
        acceptor.setDaemon(true); acceptor.start();
    }
    private void accept() {
        try {
            while (!closed) {
                LocalSocket socket = server.accept();
                boolean accepted = false;
                try {
                    if (socket.getPeerCredentials().getUid() != android.os.Process.myUid()) continue;
                    socket.setSoTimeout(5000); // Only the handshake has an idle timeout.
                    synchronized (connections) {
                        if (closed || connections.size() >= 8) continue;
                        workers.removeIf(thread -> !thread.isAlive());
                        Playback playback = new Playback(socket);
                        Thread thread = new Thread(playback, "esteria-audio-playback");
                        thread.setDaemon(true);
                        connections.add(playback); workers.add(thread);
                        thread.start(); accepted = true;
                    }
                } finally { if (!accepted) socket.close(); }
            }
        } catch (IOException | RuntimeException error) {
            if (!closed) event("audio-listener-failed");
        }
    }
    private final class Playback implements Runnable, PcmProtocol.Sink {
        private final LocalSocket socket;
        private AudioTrack track;
        private int capacity;
        private boolean ended;
        Playback(LocalSocket socket) { this.socket = socket; }
        @Override public void run() {
            try {
                try { android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO); }
                catch (SecurityException | IllegalArgumentException denied) { event("audio-priority-unavailable"); }
                new PcmProtocol().run(socket.getInputStream(), socket.getOutputStream(), this);
            } catch (IOException | RuntimeException error) { if (!closed) event("audio-stream-failed"); }
            finally { close(); synchronized (connections) { connections.remove(this); } }
        }
        @Override public synchronized void configure(int frames) throws IOException {
            capacity = frames; reset(); socket.setSoTimeout(0);
        }
        private void check() throws IOException {
            if (ended || track == null) throw new IOException("Audio stream is closed");
        }
        private void buffer() throws IOException {
            if (track.setBufferSizeInFrames(capacity) < 1) throw new IOException("Audio buffer size was rejected");
            int threshold = Build.VERSION.SDK_INT >= 31 ? track.setStartThresholdInFrames(1) : track.getBufferSizeInFrames();
            if (threshold < 1 || threshold > capacity)
                throw new IOException("Audio start threshold exceeds the producer buffer");
        }
        @Override public synchronized void reset() throws IOException {
            if (ended) throw new IOException("Audio stream is closed");
            if (track != null) { track.release(); track = null; }
            int minimum = AudioTrack.getMinBufferSize(PcmProtocol.RATE, AudioFormat.CHANNEL_OUT_STEREO,
                    AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IOException("Stereo PCM playback is unavailable");
            track = new AudioTrack.Builder().setAudioAttributes(attributes)
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(PcmProtocol.RATE)
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_STEREO).build())
                    .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(Math.max(minimum, capacity * 4)).build();
            if (track.getState() != AudioTrack.STATE_INITIALIZED) throw new IOException("Android audio initialization failed");
            buffer(); track.setVolume(volume);
        }
        @Override public synchronized void start() throws IOException { check(); buffer(); track.play(); }
        @Override public synchronized void stop() throws IOException { check(); track.pause(); track.flush(); }
        @Override public synchronized int playbackHead() throws IOException {
            check();
            // Android can change thresholds following an output route change.
            if (Build.VERSION.SDK_INT >= 31 && track.getStartThresholdInFrames() > capacity) buffer();
            return track.getPlaybackHeadPosition();
        }
        @Override public synchronized int write(byte[] bytes, int length) throws IOException {
            check(); return track.write(bytes, 0, length, AudioTrack.WRITE_NON_BLOCKING);
        }
        synchronized void volume(float value) { if (track != null) track.setVolume(value); }
        @Override public synchronized void close() {
            ended = true;
            if (track != null) { track.release(); track = null; }
            // Like accept, another thread's blocking read can retain the
            // underlying socket after close(fd); shutdown wakes that read.
            try { socket.shutdownInput(); socket.shutdownOutput(); }
            catch (IOException ignored) { /* Closing still follows; joins verify the worker stops. */ }
            try { socket.close(); } catch (IOException ignored) { /* A second close is harmless. */ }
        }
    }
    /** Call off the UI thread; shutdown has one aggregate three-second worker budget. */
    @Override public void close() throws IOException {
        closed = true;
        IOException failure = null;
        try { BridgePaths.stopAccept(server); } catch (IOException error) { failure = error; }
        try { if (server != null) server.close(); } catch (IOException error) { failure = error; }
        try { bound.close(); } catch (IOException error) { if (failure == null) failure = error; }
        List<Playback> active; List<Thread> pending;
        synchronized (connections) { active = new ArrayList<>(connections); pending = new ArrayList<>(workers); }
        for (Playback playback : active) playback.close();
        if (acceptor != null) pending.add(acceptor);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        for (Thread thread : pending) {
            long remaining = deadline - System.nanoTime();
            try { if (remaining > 0) thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(remaining))); }
            catch (InterruptedException error) { Thread.currentThread().interrupt(); failure = new IOException("Audio shutdown interrupted", error); }
            if (thread.isAlive()) failure = new IOException("Audio worker did not stop");
        }
        if (focusRequested) { manager.abandonAudioFocusRequest(focus); focusRequested = false; }
        if (ownsPath) {
            try { BridgePaths.deleteOwnedSocket(path, device, inode); ownsPath = false; }
            catch (IOException error) { if (failure == null) failure = error; else failure.addSuppressed(error); }
        }
        if (failure != null) throw failure;
    }
}
