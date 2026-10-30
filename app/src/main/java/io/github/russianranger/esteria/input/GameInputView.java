package io.github.russianranger.esteria.input;

import android.content.Context;
import android.hardware.input.InputManager;
import android.text.InputType;
import android.view.Choreographer;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.KeyCharacterMap;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.inputmethod.BaseInputConnection;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputMethodManager;
import io.github.russianranger.esteria.core.input.GameInputRouter;
import io.github.russianranger.esteria.core.input.KeyboardText;
import io.github.russianranger.esteria.core.presentation.InputSink;
import io.github.russianranger.esteria.presentation.SurfaceBridge;
import java.io.IOException;

/** Real Surface/input endpoint. The session owner must supply connected qualified bridges. */
public final class GameInputView extends SurfaceView implements SurfaceHolder.Callback,
        InputManager.InputDeviceListener, Choreographer.FrameCallback {
    public interface Events { void failed(String reason); void cursorModeChanged(boolean enabled); void rejected(String reason); }
    private final InputSink sink;
    private final GameInputRouter router;
    private final SurfaceBridge presentation;
    private final Events events;
    private final InputManager inputs;
    private int frameWidth, frameHeight, controller = -1, touch = -1;
    private boolean attached, ticking, failed, keyboard, surfaceReady, sessionPaused;
    private long keyboardGeneration;
    private long previousFrame;
    public GameInputView(Context context, InputSink sink, SurfaceBridge presentation, Events events) {
        super(context);
        this.sink = sink; this.router = new GameInputRouter(sink);
        this.presentation = presentation; this.events = events;
        inputs = (InputManager)context.getSystemService(Context.INPUT_SERVICE);
        setFocusable(true); setFocusableInTouchMode(true);
        setContentDescription("Game display. Controller Y switches between camera and pointer controls.");
        getHolder().addCallback(this);
    }
    public void frameSize(int width, int height) {
        if (width <= 0 || height <= 0 || width > 1280 || height > 768 || (long)width * height > 1280 * 720) {
            fail("Invalid game frame geometry"); return;
        }
        frameWidth = width; frameHeight = height; startTick();
    }
    private interface Action { void run() throws IOException; }
    private boolean act(Action action) {
        if (failed) return false;
        try { action.run(); return true; }
        catch (KeyboardText.RejectedText rejection) { if (events != null) events.rejected(rejection.getMessage()); return false; }
        catch (IOException | RuntimeException error) { fail(error.getMessage()); return false; }
    }
    private void fail(String reason) {
        if (failed) return;
        failed = true; keyboard = false; keyboardGeneration++; stopTick();
        try { sink.releaseAll(); } catch (IOException ignored) { /* Broken transport also releases on guest EOF. */ }
        if (events != null) events.failed(reason == null ? "Game input failed" : reason);
    }
    /** Session pause/focus loss must neutralize injected keys even while no frame is drawn. */
    public void pauseInput() { sessionPaused = true; neutralize(true); }
    public void resumeInput() { sessionPaused = false; startTick(); }
    private void neutralize(boolean cancelKeyboard) {
        stopTick(); touch = -1;
        if (cancelKeyboard) { keyboard = false; keyboardGeneration++; }
        act(router::release);
    }
    public void showKeyboard() {
        if (sessionPaused || failed || !attached || !surfaceReady || frameWidth == 0 || !hasWindowFocus()) {
            if (events != null) events.rejected("Game input is suspended"); return;
        }
        neutralize(true); if (failed) return;
        keyboard = true; keyboardGeneration++; requestFocus();
        InputMethodManager ime = (InputMethodManager)getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        if (ime != null) ime.restartInput(this);
        if (ime == null || !ime.showSoftInput(this, InputMethodManager.SHOW_IMPLICIT)) {
            keyboard = false; keyboardGeneration++; startTick();
            if (events != null) events.rejected("Software keyboard is unavailable");
        }
    }
    public void hideKeyboard() {
        keyboard = false; keyboardGeneration++;
        InputMethodManager ime = (InputMethodManager)getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        if (ime != null) ime.hideSoftInputFromWindow(getWindowToken(), 0);
        startTick();
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        frameWidth = frameHeight = 0;
        surfaceReady = act(() -> presentation.attach(holder.getSurface())); startTick();
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceReady = false; frameWidth = frameHeight = 0; neutralize(true); presentation.detach();
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow(); attached = true;
        if (inputs != null) inputs.registerInputDeviceListener(this, null); startTick();
    }
    @Override protected void onDetachedFromWindow() {
        neutralize(true); attached = surfaceReady = false;
        if (inputs != null) inputs.unregisterInputDeviceListener(this);
        presentation.detach(); super.onDetachedFromWindow();
    }
    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) startTick(); else neutralize(true);
    }
    private boolean controlsReady() {
        return attached && surfaceReady && frameWidth > 0 && !failed && !keyboard && !sessionPaused && hasWindowFocus();
    }
    private void startTick() {
        if (!controlsReady() || ticking) return;
        ticking = true; previousFrame = 0; Choreographer.getInstance().postFrameCallback(this);
    }
    private void stopTick() { ticking = false; previousFrame = 0; Choreographer.getInstance().removeFrameCallback(this); }
    @Override public void doFrame(long nanos) {
        if (!ticking) return;
        if (previousFrame != 0) act(() -> router.step((nanos - previousFrame) / 1_000_000_000.0));
        previousFrame = nanos;
        if (ticking) Choreographer.getInstance().postFrameCallback(this);
    }
    @Override public void onInputDeviceAdded(int id) { }
    @Override public void onInputDeviceChanged(int id) { if (id == controller) neutralize(false); startTick(); }
    @Override public void onInputDeviceRemoved(int id) { if (id == controller) { controller = -1; neutralize(false); startTick(); } }
    private boolean selectController(int id) {
        if (controller == id) return true;
        if (controller != -1) {
            if (!act(router::release)) return false;
            touch = -1;
        }
        controller = id; return true;
    }
    private static float axis(MotionEvent event, int code) {
        InputDevice device = event.getDevice();
        InputDevice.MotionRange range = device == null ? null : device.getMotionRange(code, event.getSource());
        if (range == null) return 0;
        float value = event.getAxisValue(code);
        if (Math.abs(value) <= Math.max(.05f, range.getFlat())) return 0;
        return Math.max(-1, Math.min(1, value));
    }
    @Override public boolean onGenericMotionEvent(MotionEvent event) {
        if ((event.getSource() & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK && event.getActionMasked() == MotionEvent.ACTION_MOVE) {
            if (!controlsReady()) return true;
            if (!selectController(event.getDeviceId())) return true;
            return act(() -> { router.sticks(axis(event, MotionEvent.AXIS_X), axis(event, MotionEvent.AXIS_Y),
                    axis(event, MotionEvent.AXIS_Z), axis(event, MotionEvent.AXIS_RZ),
                    Math.max(axis(event, MotionEvent.AXIS_LTRIGGER), axis(event, MotionEvent.AXIS_BRAKE)),
                    Math.max(axis(event, MotionEvent.AXIS_RTRIGGER), axis(event, MotionEvent.AXIS_GAS)));
                router.hat(axis(event,MotionEvent.AXIS_HAT_X),axis(event,MotionEvent.AXIS_HAT_Y)); });
        }
        return super.onGenericMotionEvent(event);
    }
    private static GameInputRouter.Button mapping(int code) {
        switch (code) {
            case KeyEvent.KEYCODE_BUTTON_A: return GameInputRouter.Button.A;
            case KeyEvent.KEYCODE_BUTTON_B: return GameInputRouter.Button.B;
            case KeyEvent.KEYCODE_BUTTON_X: return GameInputRouter.Button.X;
            case KeyEvent.KEYCODE_BUTTON_Y: return GameInputRouter.Button.Y;
            case KeyEvent.KEYCODE_BUTTON_L1: return GameInputRouter.Button.LB;
            case KeyEvent.KEYCODE_BUTTON_R1: return GameInputRouter.Button.RB;
            case KeyEvent.KEYCODE_BUTTON_L2: return GameInputRouter.Button.LT;
            case KeyEvent.KEYCODE_BUTTON_R2: return GameInputRouter.Button.RT;
            case KeyEvent.KEYCODE_BUTTON_START: return GameInputRouter.Button.START;
            case KeyEvent.KEYCODE_BUTTON_SELECT: return GameInputRouter.Button.SELECT;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return GameInputRouter.Button.L3;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return GameInputRouter.Button.R3;
            case KeyEvent.KEYCODE_DPAD_UP: return GameInputRouter.Button.UP;
            case KeyEvent.KEYCODE_DPAD_DOWN: return GameInputRouter.Button.DOWN;
            case KeyEvent.KEYCODE_DPAD_LEFT: return GameInputRouter.Button.LEFT;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return GameInputRouter.Button.RIGHT;
            default: return null;
        }
    }
    @Override public boolean onKeyPreIme(int code, KeyEvent event) {
        if (keyboard && code == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP) hideKeyboard();
        return super.onKeyPreIme(code, event);
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        GameInputRouter.Button button = mapping(event.getKeyCode());
        InputDevice device = event.getDevice();
        boolean gamepad = event.isFromSource(InputDevice.SOURCE_GAMEPAD) || event.isFromSource(InputDevice.SOURCE_JOYSTICK) ||
                (device != null && (device.supportsSource(InputDevice.SOURCE_GAMEPAD) || device.supportsSource(InputDevice.SOURCE_JOYSTICK)));
        if (button != null && gamepad) {
            if (!controlsReady()) return true;
            if (event.getAction() != KeyEvent.ACTION_DOWN && event.getAction() != KeyEvent.ACTION_UP) return true;
            if (!selectController(event.getDeviceId())) return true;
            boolean oldMode = router.cursorMode();
            boolean result = act(() -> router.button(button, event.getAction() == KeyEvent.ACTION_DOWN));
            if (events != null && oldMode != router.cursorMode()) events.cursorModeChanged(router.cursorMode());
            return result;
        }
        return super.dispatchKeyEvent(event);
    }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (!controlsReady()) return false;
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN) { requestFocus(); touch = event.getPointerId(0); }
        if (action == MotionEvent.ACTION_CANCEL) { touch = -1; return act(router::release); }
        int index = event.findPointerIndex(touch);
        if (index < 0) return true;
        boolean down = action != MotionEvent.ACTION_UP &&
                !(action == MotionEvent.ACTION_POINTER_UP && event.getPointerId(event.getActionIndex()) == touch);
        boolean result = act(() -> router.touch(event.getX(index), event.getY(index), getWidth(), getHeight(), frameWidth, frameHeight, down));
        if (!down) { touch = -1; performClick(); }
        return result;
    }
    @Override public boolean performClick() { super.performClick(); return true; }
    @Override public boolean onCheckIsTextEditor() { return true; }
    @Override public InputConnection onCreateInputConnection(EditorInfo info) {
        info.inputType = InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS;
        info.imeOptions = EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI | EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING;
        final long generation = keyboardGeneration;
        return new BaseInputConnection(this, false) {
            private final KeyboardText.Composition composing = new KeyboardText.Composition();
            private boolean ready() {
                boolean valid = !failed && keyboard && !sessionPaused && attached && surfaceReady && hasWindowFocus() && generation == keyboardGeneration;
                if (!valid) composing.clear();
                return valid;
            }
            @Override public boolean commitText(CharSequence text, int position) {
                return ready() && act(() -> composing.commit(sink, text));
            }
            @Override public boolean setComposingText(CharSequence text, int position) {
                return ready() && composing.stage(text);
            }
            @Override public boolean finishComposingText() {
                return ready() && act(() -> composing.finish(sink));
            }
            @Override public boolean deleteSurroundingText(int before, int after) {
                if (!ready() || after != 0 || before < 0 || before > 64) return false;
                return act(() -> composing.delete(sink, before));
            }
            @Override public boolean performEditorAction(int action) {
                boolean result = finishComposingText(); if (result) hideKeyboard(); return result;
            }
            @Override public boolean sendKeyEvent(KeyEvent event) {
                if (!ready()) return false;
                if (event.getAction() != KeyEvent.ACTION_DOWN) return true;
                if (event.getKeyCode() == KeyEvent.KEYCODE_DEL) return act(() -> composing.delete(sink, 1));
                if (event.getKeyCode() == KeyEvent.KEYCODE_ENTER) return act(() -> composing.enter(sink));
                int code = event.getUnicodeChar();
                if ((code & KeyCharacterMap.COMBINING_ACCENT) != 0 || !Character.isValidCodePoint(code)) {
                    if (events != null) events.rejected("Dead-key composition is not supported by this keyboard bridge");
                    return false;
                }
                return code != 0 && commitText(new String(Character.toChars(code)), 1);
            }
        };
    }
}
