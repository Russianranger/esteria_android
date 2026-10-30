package io.github.russianranger.esteria.presentation;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.media.Image;
import android.media.ImageReader;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.system.Os;
import android.system.StructStat;
import android.view.SurfaceHolder;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.MainActivity;
import io.github.russianranger.esteria.core.presentation.InputSink;
import io.github.russianranger.esteria.input.GameInputView;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real Android sockets, JNI/ANativeWindow, ImageReader and AudioTrack; synthetic producers only. */
@RunWith(AndroidJUnit4.class)
public final class PresentationAudioTest {
    private static final int FRAME_MAGIC = 0x54524631, PCM_MAGIC = 0x50414c54;
    private static void waitFor(java.util.function.BooleanSupplier condition, int millis, String message) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(millis);
        while (!condition.getAsBoolean() && System.nanoTime() < deadline) Thread.sleep(10);
        assertTrue(message, condition.getAsBoolean());
    }
    private static void word(DataOutputStream output, int value) throws IOException { output.writeInt(Integer.reverseBytes(value)); }
    private static int word(DataInputStream input) throws IOException { return Integer.reverseBytes(input.readInt()); }
    private static LocalSocket connect(Path directory, String name) throws IOException {
        LocalSocket socket = new LocalSocket();
        try {
            socket.connect(new LocalSocketAddress(directory.resolve(name).toString(), LocalSocketAddress.Namespace.FILESYSTEM));
            socket.setSoTimeout(3000); return socket;
        } catch (IOException error) { socket.close(); throw error; }
    }

    static final class Frames implements AutoCloseable {
        final LocalSocket bound = new LocalSocket();
        final LocalServerSocket server;
        final Thread worker;
        final String path;
        final long device, inode;
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        final AtomicInteger connections = new AtomicInteger(), peerEofs = new AtomicInteger();
        final boolean malformed, holdAfterFirstFrame;
        volatile LocalSocket current;
        volatile boolean closed;
        Frames(Path directory, boolean malformed) throws Exception {
            this(directory, malformed, false);
        }
        Frames(Path directory, boolean malformed, boolean holdAfterFirstFrame) throws Exception {
            this.malformed = malformed; this.holdAfterFirstFrame = holdAfterFirstFrame;
            path = directory.resolve("frame.sock").toString();
            assertFalse(Files.exists(directory.resolve("frame.sock")));
            bound.bind(new LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM)); Os.chmod(path, 0600);
            StructStat stat = Os.lstat(path); device = stat.st_dev; inode = stat.st_ino;
            server = new LocalServerSocket(bound.getFileDescriptor());
            worker = new Thread(this::serve, "esteria-synthetic-frame-producer"); worker.start();
        }
        private void serve() {
            try {
                while (!closed) {
                    try (LocalSocket socket = server.accept()) {
                        if (closed) break; // The owned accept-wakeup is not a presentation connection.
                        current = socket; socket.setSoTimeout(3000);
                        int connection = connections.incrementAndGet();
                        DataInputStream input = new DataInputStream(socket.getInputStream());
                        DataOutputStream output = new DataOutputStream(socket.getOutputStream());
                        int sequence = 0, width = connection == 1 ? 2 : 3, height = connection == 1 ? 2 : 1;
                        while (!closed) {
                            int request = input.read();
                            if (request == -1) { peerEofs.incrementAndGet(); break; }
                            assertEquals(1, request); sequence++;
                            // Keep the native receiver blocked after one posted frame. A
                            // pause must shut down its socket; no racing reply is needed
                            // to prove the producer actually receives peer EOF.
                            if (holdAfterFirstFrame && sequence > 1) continue;
                            boolean unchanged = malformed || sequence > 1;
                            int[] header = {FRAME_MAGIC, width, height, width * 4, 17, sequence,
                                    unchanged ? 0 : width * height * 4, unchanged ? 2 : 0};
                            for (int value : header) output.writeInt(value);
                            if (!unchanged) for (int pixel = 0; pixel < width * height; ++pixel)
                                output.writeInt(Integer.reverseBytes(0x00112233 + pixel));
                            output.flush(); Thread.sleep(10);
                        }
                    } catch (IOException disconnected) {
                        // Surface retirement closes its connection while a reply may be in flight.
                    } finally { current = null; }
                }
            } catch (Throwable error) { failure.set(error); }
        }
        @Override public void close() throws Exception {
            closed = true;
            LocalSocket socket = current;
            if (socket != null) socket.close();
            BridgePaths.stopAccept(server);
            server.close(); bound.close(); worker.join(4000);
            assertFalse("Synthetic frame producer must stop: " + Arrays.toString(worker.getStackTrace()), worker.isAlive());
            BridgePaths.deleteOwnedSocket(path, device, inode);
            if (failure.get() != null) throw new AssertionError("Synthetic frame producer failed", failure.get());
        }
    }

    /** Records Java input calls only; this fixture does not inject X11 events. */
    private static final class RecordingInput implements InputSink {
        final AtomicInteger calls = new AtomicInteger(), releases = new AtomicInteger();
        public void key(int keysym, boolean down) { calls.incrementAndGet(); }
        public void keySequence(int[] keys, boolean[] down) { calls.incrementAndGet(); }
        public void pointer(int x, int y, int mask) { calls.incrementAndGet(); }
        public void relativeMotion(int dx, int dy) { calls.incrementAndGet(); }
        public void buttons(int mask) { calls.incrementAndGet(); }
        public void releaseAll() { releases.incrementAndGet(); }
    }

    private static void pausedSurfaceLifecycle(android.app.Instrumentation instrumentation,
                                               Activity activity, Context context, Path root) throws Exception {
        AtomicReference<GameInputView> view = new AtomicReference<>();
        AtomicReference<String> failure = new AtomicReference<>();
        AtomicInteger created = new AtomicInteger(), destroyed = new AtomicInteger();
        RecordingInput input = new RecordingInput();
        try (Frames producer = new Frames(root, false, true);
             SurfaceBridge bridge = new SurfaceBridge(context, root.toFile(), new SurfaceBridge.Events() {
                 public void frameSize(int width, int height) { view.get().frameSize(width, height); }
                 public void failed(String reason) { failure.set(reason); }
             })) {
            try {
                instrumentation.runOnMainSync(() -> {
                    GameInputView display = new GameInputView(activity, input, bridge, new GameInputView.Events() {
                        public void failed(String reason) { failure.set(reason); }
                        public void cursorModeChanged(boolean enabled) { }
                        public void rejected(String reason) { failure.set(reason); }
                    });
                    view.set(display);
                    display.getHolder().addCallback(new SurfaceHolder.Callback() {
                        public void surfaceCreated(SurfaceHolder holder) { created.incrementAndGet(); }
                        public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { }
                        public void surfaceDestroyed(SurfaceHolder holder) { destroyed.incrementAndGet(); }
                    });
                    display.pauseInput();
                    ViewGroup content = activity.findViewById(android.R.id.content);
                    content.addView(display, new FrameLayout.LayoutParams(320, 180));
                });
                waitFor(() -> created.get() == 1, 8000, "Paused view must receive a real surface-created callback");
                Thread.sleep(200);
                assertEquals("Paused surface creation must not connect", 0, producer.connections.get());
                assertEquals("Paused surface creation must not post native frames", 0, bridge.counters()[0]);
                assertNull(failure.get());

                instrumentation.runOnMainSync(() -> view.get().resumeInput());
                waitFor(() -> bridge.counters()[0] == 1, 4000, "Resume must post a real native SurfaceView frame");
                assertEquals(1, producer.connections.get());
                instrumentation.runOnMainSync(() -> view.get().pauseInput());
                waitFor(() -> producer.peerEofs.get() == 1, 4000, "Pause must reach the producer as peer EOF");

                instrumentation.runOnMainSync(() -> view.get().setVisibility(View.GONE));
                waitFor(() -> destroyed.get() == 1, 8000, "GONE must destroy the actual SurfaceView surface");
                instrumentation.runOnMainSync(() -> view.get().setVisibility(View.VISIBLE));
                waitFor(() -> created.get() == 2, 8000, "VISIBLE must recreate the actual SurfaceView surface");
                Thread.sleep(200);
                assertEquals("Paused recreation must not reconnect", 1, producer.connections.get());
                assertEquals("Paused recreation must not post another frame", 1, bridge.counters()[0]);
                assertNull(failure.get());

                instrumentation.runOnMainSync(() -> view.get().resumeInput());
                waitFor(() -> bridge.counters()[0] == 2, 4000, "Resume after recreation must post a second native frame");
                instrumentation.runOnMainSync(() -> { view.get().resumeInput(); view.get().resumeInput(); });
                Thread.sleep(200);
                assertEquals("Repeated resume must retain one writer", 2, producer.connections.get());
                assertEquals(2, bridge.counters()[0]);
                assertNull(failure.get());
            } finally {
                instrumentation.runOnMainSync(() -> {
                    GameInputView display = view.get();
                    if (display != null) {
                        display.pauseInput();
                        if (display.getParent() instanceof ViewGroup) ((ViewGroup)display.getParent()).removeView(display);
                    }
                });
            }
            waitFor(() -> producer.peerEofs.get() == 2, 4000, "Removal must retire the second native writer");
            waitFor(() -> destroyed.get() == 2, 4000, "Removal must destroy the recreated surface");
            assertEquals(2, producer.connections.get());
            assertTrue("Pauses must neutralize the recording input sink", input.releases.get() >= 3);
            assertNull(failure.get());
        }
        assertFalse("Lifecycle fixture must remove its owned frame socket", Files.exists(root.resolve("frame.sock")));
    }
    private static final class Readback implements AutoCloseable {
        final ImageReader reader;
        final CountDownLatch received = new CountDownLatch(1);
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        Readback(int width, int height, Handler handler) {
            reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3);
            reader.setOnImageAvailableListener(source -> {
                boolean observed = false;
                try (Image image = source.acquireLatestImage()) {
                    if (image == null) return;
                    observed = true;
                    assertEquals(width, image.getWidth()); assertEquals(height, image.getHeight());
                    assertEquals(1, image.getPlanes().length);
                    Image.Plane plane = image.getPlanes()[0]; ByteBuffer pixels = plane.getBuffer();
                    assertEquals(4, plane.getPixelStride()); assertTrue(plane.getRowStride() >= width * 4);
                    for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
                        int offset = y * plane.getRowStride() + x * plane.getPixelStride();
                        assertEquals(0x11, pixels.get(offset) & 255);
                        assertEquals(0x22, pixels.get(offset + 1) & 255);
                        assertEquals(0x33 + y * width + x, pixels.get(offset + 2) & 255);
                        assertEquals(255, pixels.get(offset + 3) & 255);
                    }
                } catch (Throwable error) { observed = true; failure.set(error); }
                finally { if (observed) received.countDown(); }
            }, handler);
        }
        void await() throws Exception {
            assertTrue("Real Android ImageReader must receive native-posted pixels", received.await(8, TimeUnit.SECONDS));
            if (failure.get() != null) throw new AssertionError("Android pixel readback failed", failure.get());
        }
        @Override public void close() { reader.close(); }
    }

    @Test public void actualSurfaceAndAudioTrackContracts() throws Exception {
        android.app.Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        Context context = instrumentation.getTargetContext();
        assertEquals(33, Build.VERSION.SDK_INT); assertEquals(35, context.getApplicationInfo().targetSdkVersion);
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        assertTrue("Explicit emulator-only JNI build is mandatory", BuildConfig.PRESENTATION_EMULATOR_TEST);
        assertFalse(BuildConfig.PROOT_PACKAGED);
        Path root = Files.createTempDirectory(context.getFilesDir().toPath(), "av-"); Os.chmod(root.toString(), 0700);
        Activity activity = instrumentation.startActivitySync(new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        instrumentation.waitForIdleSync();
        HandlerThread callbacks = new HandlerThread("esteria-image-readback"); callbacks.start();
        Handler handler = new Handler(callbacks.getLooper());
        long acceptedFrames = 0, playedFrames = 0;
        try {
            assertEquals(root.toRealPath(), BridgePaths.directory(context, root.toFile()));
            Path child = Files.createDirectory(root.resolve("real")); Os.chmod(child.toString(), 0700);
            Path link = root.resolve("linked"); Files.createSymbolicLink(link, child);
            try { BridgePaths.directory(context, link.toFile()); fail("Child symlinks cannot become bridge roots"); }
            catch (IOException expected) { }
            Files.delete(link); Files.delete(child);

            AtomicReference<String> surfaceFailure = new AtomicReference<>();
            SurfaceBridge.Events events = new SurfaceBridge.Events() {
                public void frameSize(int width, int height) { }
                public void failed(String reason) { surfaceFailure.set(reason); }
            };
            try (Frames producer = new Frames(root, false);
                 Readback first = new Readback(2, 2, handler); Readback second = new Readback(3, 1, handler);
                 SurfaceBridge bridge = new SurfaceBridge(context, root.toFile(), events)) {
                bridge.attach(first.reader.getSurface()); first.await();
                waitFor(() -> bridge.counters()[1] > 0, 4000, "Unchanged Android frame response must be observed");
                bridge.detach(); bridge.attach(second.reader.getSurface()); second.await();
                waitFor(() -> bridge.counters()[0] >= 2, 4000, "Both native frame posts must complete");
                assertNull("Surface recreation must not fail", surfaceFailure.get());
            }
            assertFalse(Files.exists(root.resolve("frame.sock")));
            CountDownLatch rejected = new CountDownLatch(1);
            try (Frames producer = new Frames(root, true); Readback readback = new Readback(2, 2, handler);
                 SurfaceBridge bridge = new SurfaceBridge(context, root.toFile(), new SurfaceBridge.Events() {
                     public void frameSize(int width, int height) { }
                     public void failed(String reason) { rejected.countDown(); }
                 })) {
                bridge.attach(readback.reader.getSurface());
                assertTrue("Invalid initial unchanged frame must fail", rejected.await(6, TimeUnit.SECONDS));
                assertEquals(0, bridge.counters()[0]); assertEquals(1, readback.received.getCount());
            }

            pausedSurfaceLifecycle(instrumentation, activity, context, root);

            List<String> audioEvents = Collections.synchronizedList(new java.util.ArrayList<>());
            try (AudioBridge audio = AudioBridge.start(context, root.toFile(), audioEvents::add);
                 LocalSocket socket = connect(root, "audio.sock")) {
                assertTrue("Foreground fixture must obtain audio focus", audioEvents.contains("audio-focus-gained"));
                DataInputStream input = new DataInputStream(socket.getInputStream());
                DataOutputStream output = new DataOutputStream(socket.getOutputStream());
                for (int value : new int[]{PCM_MAGIC, 1, 48000, 2, 1920}) word(output, value);
                output.flush(); assertEquals(0, word(input)); word(output, 1); output.flush(); assertEquals(0, word(input));
                byte[] pcm = new byte[480 * 4]; Arrays.fill(pcm, (byte)0x12);
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(8);
                while (acceptedFrames < 4800 && System.nanoTime() < deadline) {
                    word(output, 4); word(output, 480); output.write(pcm); output.flush();
                    int accepted = word(input); assertTrue(accepted >= 0 && accepted <= 480); acceptedFrames += accepted;
                    word(output, 3); output.flush(); playedFrames = Integer.toUnsignedLong(word(input));
                    if (accepted == 0) Thread.sleep(5);
                }
                assertTrue("Real AudioTrack must accept streamed PCM", acceptedFrames >= 4800);
                while (playedFrames < acceptedFrames && System.nanoTime() < deadline) {
                    Thread.sleep(10); word(output, 3); output.flush(); playedFrames = Integer.toUnsignedLong(word(input));
                }
                assertTrue("Real AudioTrack playback head must consume accepted PCM", playedFrames >= acceptedFrames);
                word(output, 2); output.flush(); assertEquals(0, word(input));
                word(output, 5); output.flush(); assertEquals(0, word(input));
                word(output, 3); output.flush(); assertEquals(0, word(input));
            }
            assertFalse(Files.exists(root.resolve("audio.sock")));
            try (AudioBridge audio = AudioBridge.start(context, root.toFile(), null)) {
                try (LocalSocket invalid = connect(root, "audio.sock")) {
                    DataOutputStream output = new DataOutputStream(invalid.getOutputStream());
                    word(output, 0); output.flush(); assertEquals(-1, invalid.getInputStream().read());
                }
                try (LocalSocket recovered = connect(root, "audio.sock")) {
                    DataOutputStream output = new DataOutputStream(recovered.getOutputStream());
                    for (int value : new int[]{PCM_MAGIC,1,48000,2,64}) word(output, value);
                    output.flush(); assertEquals(0, word(new DataInputStream(recovered.getInputStream())));
                    // The owner must stop an established idle worker while
                    // its peer remains connected, not depend on peer EOF.
                    audio.close();
                    assertEquals(-1, recovered.getInputStream().read());
                }
            }
            assertFalse(Files.exists(root.resolve("audio.sock")));
            JSONObject receipt = new JSONObject().put("formatVersion",1)
                    .put("scope","android-13-x86_64-surface-audiotrack-protocol-fixtures")
                    .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("api",Build.VERSION.SDK_INT)
                    .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("fingerprint",Build.FINGERPRINT)
                    .put("abi","x86_64").put("groupsPassed",6).put("nativeSurfaceExecuted",true)
                    .put("rgbaReadbackVerified",true).put("surfaceRecreationVerified",true)
                    .put("invalidFrameRejected",true).put("audioTrackAcceptedFrames",acceptedFrames)
                    .put("audioTrackPlayedFrames",playedFrames).put("audioResetVerified",true)
                    .put("audioInvalidHandshakeRecovered",true).put("privateSocketCleanupVerified",true)
                    .put("audioActivePeerShutdownVerified",true)
                    .put("pausedSurfaceCreationBlocked",true).put("surfaceResumeFrameVerified",true)
                    .put("surfacePausePeerEofVerified",true).put("pausedSurfaceRecreationBlocked",true)
                    .put("surfaceResumeIdempotentVerified",true).put("surfaceLifecycleCleanupVerified",true)
                    .put("surfaceLifecycleConnections",2).put("surfaceLifecyclePeerEofs",2)
                    .put("privateRootAliasVerified",true).put("privateChildSymlinkRejected",true)
                    .put("arm64GuestExecuted",false).put("androidWineExecuted",false).put("x11GuestExecuted",false)
                    .put("audibleOutputQualified",false).put("adrenoQualified",false).put("gameplayQualified",false);
            Files.write(context.getFilesDir().toPath().resolve("presentation-audio-qualification.json"),
                    receipt.toString(2).getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
        } finally {
            callbacks.quitSafely(); callbacks.join(4000); assertFalse(callbacks.isAlive());
            instrumentation.runOnMainSync(activity::finish);
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
}
