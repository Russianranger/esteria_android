package io.github.russianranger.esteria.presentation;

import android.app.Instrumentation;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Test-only framework device registration; this does not inject evdev packets.
 * Android 13's interactive protocol and EOF removal are documented at:
 * https://github.com/aosp-mirror/platform_frameworks_base/blob/android-13.0.0_r1/cmds/uinput/README.md
 * Its real range mapping comes from the same revision's data/keyboards/Generic.kl.
 * The test must still observe the actual image's device and never invent ranges.
 */
@android.annotation.TargetApi(33)
final class RegisteredInputFixture implements AutoCloseable {
    static final String AVAILABLE = "none";
    static final String UNAVAILABLE = "registration-not-observed";
    private static final String NAME = "Esteria-Component-Gamepad";
    private static final int VENDOR = 0x1234, PRODUCT = 0xe57a;
    private static final int[] AXES = {MotionEvent.AXIS_X, MotionEvent.AXIS_Y,
        MotionEvent.AXIS_Z, MotionEvent.AXIS_RZ, MotionEvent.AXIS_GAS,
        MotionEvent.AXIS_BRAKE, MotionEvent.AXIS_HAT_X, MotionEvent.AXIS_HAT_Y};
    private static final Object ADMISSION = new Object();
    private static Owner active;
    final InputDevice device;
    final String unavailableReason;
    private final Owner owner;

    private RegisteredInputFixture(Owner owner, InputDevice device) {
        this.owner = owner;
        this.device = device;
        unavailableReason = device == null ? UNAVAILABLE : AVAILABLE;
    }

    static RegisteredInputFixture open(Instrumentation instrumentation) throws IOException {
        if (instrumentation == null || Looper.myLooper() == Looper.getMainLooper())
            throw new IOException("Registered input fixture requires an instrumentation worker");
        Owner owner;
        synchronized (ADMISSION) {
            if (active != null) throw new IOException("Registered input fixture ownership is retained");
            owner = new Owner(instrumentation);
            active = owner;
        }
        try {
            owner.start();
            InputDevice device = owner.awaitDevice();
            if (device == null) owner.close();
            else {
                validate(device);
                if (owner.inputs.getInputDevice(device.getId()) == null)
                    throw new IOException("Registered fixture disappeared before use");
            }
            return new RegisteredInputFixture(owner, device);
        } catch (IOException | RuntimeException | Error failure) {
            try { owner.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    @Override public void close() throws IOException { owner.close(); }

    private static boolean matches(InputDevice device) {
        return device != null && NAME.equals(device.getName())
            && device.getVendorId() == VENDOR && device.getProductId() == PRODUCT;
    }

    private static void validate(InputDevice device) throws IOException {
        if (!device.supportsSource(InputDevice.SOURCE_GAMEPAD)
                || !device.supportsSource(InputDevice.SOURCE_JOYSTICK))
            throw new IOException("Registered fixture lacks gamepad or joystick sources");
        for (int axis : AXES) {
            InputDevice.MotionRange range = device.getMotionRange(axis, InputDevice.SOURCE_JOYSTICK);
            if (range == null || !Float.isFinite(range.getMin()) || !Float.isFinite(range.getMax())
                    || !Float.isFinite(range.getFlat()) || !Float.isFinite(range.getFuzz())
                    || !Float.isFinite(range.getResolution()) || Math.abs(range.getMax() - 1) > .001f
                    || range.getFlat() < 0 || range.getFuzz() < 0 || range.getResolution() < 0)
                throw new IOException("Registered fixture has an invalid real motion range");
            boolean trigger = axis == MotionEvent.AXIS_GAS || axis == MotionEvent.AXIS_BRAKE;
            if (trigger ? Math.abs(range.getMin()) > .001f
                    : Math.abs(range.getMin() + 1) > .001f)
                throw new IOException("Registered fixture has an unexpected real axis minimum");
            boolean stick = axis == MotionEvent.AXIS_X || axis == MotionEvent.AXIS_Y
                || axis == MotionEvent.AXIS_Z || axis == MotionEvent.AXIS_RZ;
            if (stick ? range.getFlat() < .05f || range.getFlat() > .08f
                    : range.getFlat() > .001f)
                throw new IOException("Registered fixture has an unexpected real axis flat");
        }
    }

    private static String registration() {
        StringBuilder json = new StringBuilder("{\"id\":1,\"command\":\"register\",\"name\":\"")
            .append(NAME).append("\",\"vid\":").append(VENDOR).append(",\"pid\":").append(PRODUCT)
            .append(",\"bus\":\"usb\",\"configuration\":[{\"type\":100,\"data\":[1,3]},")
            .append("{\"type\":101,\"data\":[304,305,307,308,310,311,312,313,314,315,317,318]},")
            .append("{\"type\":103,\"data\":[0,1,2,5,9,10,16,17]}],\"abs_info\":[");
        int[] codes = {0, 1, 2, 5, 9, 10, 16, 17};
        for (int index = 0; index < codes.length; index++) {
            if (index != 0) json.append(',');
            boolean stick = index < 4, trigger = index == 4 || index == 5;
            json.append("{\"code\":").append(codes[index]).append(",\"info\":{\"value\":0,\"minimum\":")
                .append(stick ? -32767 : trigger ? 0 : -1).append(",\"maximum\":")
                .append(stick ? 32767 : trigger ? 255 : 1)
                .append(",\"fuzz\":0,\"flat\":").append(stick ? 2048 : 0)
                .append(",\"resolution\":0}}");
        }
        return json.append("]}\n").toString();
    }

    private static final class Owner implements InputManager.InputDeviceListener {
        private static final long REGISTER_MILLIS = 5000, CLOSE_MILLIS = 4000;
        private static final int STDOUT_LIMIT = 8192;
        private final Instrumentation instrumentation;
        private final InputManager inputs;
        private final Object signal = new Object();
        private final HandlerThread listener = new HandlerThread("EsteriaFixtureInputListener");
        private final CountDownLatch outputDone = new CountDownLatch(1);
        private final Set<Integer> known = new HashSet<>(), removed = new HashSet<>();
        private InputDevice observed;
        private IOException observationFailure;
        private volatile IOException outputFailure;
        private volatile boolean outputEof;
        private InputStream stdout;
        private OutputStream stdin;
        private Thread collector;
        private boolean listening, commandStarted, closed;
        private boolean registrationWriteFailed;
        private long registrationDeadline;

        Owner(Instrumentation instrumentation) throws IOException {
            this.instrumentation = instrumentation;
            inputs = instrumentation.getTargetContext().getSystemService(InputManager.class);
            if (inputs == null) throw new IOException("Input manager unavailable for registered fixture");
        }

        void start() throws IOException {
            registrationDeadline = SystemClock.uptimeMillis() + REGISTER_MILLIS;
            // Refuse an existing matching device: no caller-supplied or unrelated
            // framework ID is ever adopted or removed by this fixture.
            for (int id : inputs.getInputDeviceIds())
                if (matches(inputs.getInputDevice(id)))
                    throw new IOException("A matching registered fixture already exists");
            listener.start();
            inputs.registerInputDeviceListener(this, new Handler(listener.getLooper()));
            listening = true;
            ParcelFileDescriptor[] pipes = instrumentation.getUiAutomation()
                .executeShellCommandRw("/system/bin/uinput -");
            commandStarted = true;
            if (pipes == null || pipes.length != 2 || pipes[0] == null || pipes[1] == null) {
                if (pipes != null) for (ParcelFileDescriptor pipe : pipes)
                    if (pipe != null) pipe.close();
                throw new IOException("Registered fixture shell pipes unavailable");
            }
            stdout = new ParcelFileDescriptor.AutoCloseInputStream(pipes[0]);
            stdin = new ParcelFileDescriptor.AutoCloseOutputStream(pipes[1]);
            collector = new Thread(() -> {
                try (InputStream source = stdout; ByteArrayOutputStream capture = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[1024];
                    int count;
                    while ((count = source.read(buffer)) != -1) {
                        if (count > STDOUT_LIMIT - capture.size())
                            throw new IOException("Registered fixture stdout exceeds its bound");
                        capture.write(buffer, 0, count);
                    }
                    outputEof = true;
                } catch (IOException error) { outputFailure = error; }
                finally { outputDone.countDown(); synchronized (signal) { signal.notifyAll(); } }
            }, "EsteriaFixtureUinputStdout");
            collector.setDaemon(true);
            collector.start();
            byte[] bytes = registration().getBytes(StandardCharsets.UTF_8);
            if (bytes.length > 4096) throw new IOException("Fixed registration exceeds its bound");
            try {
                stdin.write(bytes);
                stdin.flush();
            } catch (IOException toolClosedInput) {
                // A missing/denied tool can close its pipe before this small
                // fixed write. It is unavailable only after confirmed cleanup.
                registrationWriteFailed = true;
            }
        }

        InputDevice awaitDevice() throws IOException {
            synchronized (signal) {
                while (true) {
                    if (observationFailure != null) throw observationFailure;
                    if (outputFailure != null) throw outputFailure;
                    if (observed != null) return observed;
                    if (outputEof || registrationWriteFailed) return null;
                    long remaining = registrationDeadline - SystemClock.uptimeMillis();
                    if (remaining <= 0) return null;
                    await(signal, Math.min(remaining, 100));
                }
            }
        }

        @Override public void onInputDeviceAdded(int id) { consider(id); }
        @Override public void onInputDeviceChanged(int id) { consider(id); }
        @Override public void onInputDeviceRemoved(int id) {
            synchronized (signal) { if (known.contains(id)) removed.add(id); signal.notifyAll(); }
        }
        private void consider(int id) {
            InputDevice device = inputs.getInputDevice(id);
            if (!matches(device)) return;
            synchronized (signal) {
                known.add(id);
                if (observed != null && observed.getId() != id)
                    observationFailure = new IOException("Multiple matching fixture devices registered");
                else observed = device;
                signal.notifyAll();
            }
        }

        synchronized void close() throws IOException {
            if (closed) return;
            long deadline = SystemClock.uptimeMillis() + CLOSE_MILLIS;
            IOException failure = null;
            if (stdin != null) {
                try { stdin.close(); } catch (IOException error) { failure = error; }
                stdin = null;
            }
            if (commandStarted) {
                try {
                    if (!outputDone.await(Math.max(1, deadline - SystemClock.uptimeMillis()), TimeUnit.MILLISECONDS))
                        failure = combine(failure, new IOException("Registered fixture EOF cleanup timed out"));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    failure = combine(failure, new InterruptedIOException("Registered fixture cleanup interrupted"));
                }
                if (outputFailure != null) failure = combine(failure, outputFailure);
                if (!outputEof) failure = combine(failure, new IOException("Registered fixture EOF was not confirmed"));
            }
            // EOF closes every uinput device in Android13 Uinput.run(), and
            // native Device destruction calls UI_DEV_DESTROY. Also require the
            // actual framework removal, rather than infer it from pipe closure.
            try {
                synchronized (signal) {
                    while (commandStarted) {
                        boolean present = false;
                        for (int id : inputs.getInputDeviceIds()) {
                            InputDevice device = inputs.getInputDevice(id);
                            if (matches(device)) { known.add(id); present = true; }
                        }
                        boolean removalObserved = removed.containsAll(known);
                        if (!present && removalObserved) break;
                        long remaining = deadline - SystemClock.uptimeMillis();
                        if (remaining <= 0) throw new IOException("Registered fixture framework removal timed out");
                        await(signal, Math.min(remaining, 100));
                    }
                }
            } catch (IOException error) { failure = combine(failure, error); }
            catch (RuntimeException error) {
                failure = combine(failure, new IOException("Registered fixture removal observation failed", error));
            }
            if (stdout != null) {
                try { stdout.close(); } catch (IOException error) { failure = combine(failure, error); }
                stdout = null;
            }
            if (listening) {
                try { inputs.unregisterInputDeviceListener(this); listening = false; }
                catch (RuntimeException error) {
                    failure = combine(failure, new IOException("Registered fixture listener cleanup failed", error));
                }
            }
            listener.quitSafely();
            failure = joinWithin(collector, deadline, failure, "output collector");
            failure = joinWithin(listener, deadline, failure, "input listener");
            if (failure != null) throw failure;
            closed = true;
            synchronized (ADMISSION) { if (active == this) active = null; }
        }

        private static void await(Object signal, long millis) throws IOException {
            try { signal.wait(millis); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new InterruptedIOException("Registered fixture wait interrupted");
            }
        }
        private static IOException combine(IOException current, IOException next) {
            if (current == null) return next;
            if (current != next) current.addSuppressed(next);
            return current;
        }
        private static IOException joinWithin(Thread thread, long deadline, IOException failure, String role) {
            if (thread == null || !thread.isAlive()) return failure;
            long remaining = deadline - SystemClock.uptimeMillis();
            if (remaining > 0) {
                try { thread.join(remaining); }
                catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    failure = combine(failure, new InterruptedIOException("Registered fixture cleanup interrupted"));
                }
            }
            return thread.isAlive()
                ? combine(failure, new IOException("Registered fixture " + role + " remains alive")) : failure;
        }
    }
}
