package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import io.github.russianranger.esteria.input.GameInputView;
import java.io.IOException;
import java.util.function.Consumer;

/** A replaceable view of an existing presentation session. The session owner
 * retains processes across Activity recreation and performs requested shutdown.
 * This panel neither starts a game nor grants runtime qualification.
 */
public final class GamePresentationPanel extends FrameLayout {
    public interface Actions { void requestStop(); }

    /** Pass this relay to ClientPresentationSession.start. It belongs to that
     * session's owner and does not retain a detached Activity or its views. */
    public static final class SessionEvents implements ClientPresentationSession.Events {
        private final Handler main = new Handler(Looper.getMainLooper());
        private final Consumer<String> failureOwner;
        private GamePresentationPanel target;
        private int width, height;
        private String failure;
        public SessionEvents(Consumer<String> failureOwner) {
            if (failureOwner == null) throw new IllegalArgumentException("Session failure owner is required");
            this.failureOwner = failureOwner;
        }
        @Override public void frameSize(int width, int height) {
            main.post(() -> {
                if (failure != null) return;
                this.width = width; this.height = height;
                if (target != null) target.frameSize(width, height);
            });
        }
        @Override public void failed(String reason) {
            main.post(() -> {
                if (failure != null) return;
                failure = reason == null ? "Presentation failed" : reason;
                if (target != null) target.showFailure();
                failureOwner.accept(failure);
            });
        }
        private void attach(GamePresentationPanel panel) {
            uiThread();
            if (target != null && target != panel) throw new IllegalStateException("Another presentation view is attached");
            target = panel;
            if (failure != null) panel.showFailure();
            else if (width > 0) panel.frameSize(width, height);
        }
        private void detach(GamePresentationPanel panel) { uiThread(); if (target == panel) target = null; }
    }

    private final SessionEvents events;
    private final FrameLayout viewport;
    private final TextView message;
    private final Actions actions;
    private boolean keyboardRequested;
    private ClientPresentationSession session;
    private GameInputView game;
    private boolean attached, foreground, failed, stopRequested;
    private int videoWidth, videoHeight;

    public GamePresentationPanel(Context context, SessionEvents events, Actions actions) {
        super(context); uiThread();
        if (events == null || actions == null) throw new IllegalArgumentException("Session events and stop owner are required");
        this.events = events;
        setBackgroundColor(Color.BLACK);
        this.actions = actions;
        viewport = new FrameLayout(context);
        viewport.addOnLayoutChangeListener((view, left, top, right, bottom, oldLeft, oldTop, oldRight, oldBottom) -> fitGame());
        addView(viewport,new FrameLayout.LayoutParams(-1,-1));
        message = new TextView(context);
        message.setText("Connecting display…");
    }

    public void setLookPercent(int percent){if(game!=null)game.setLookPercent(percent);}
    public String inputStatus(){return message.getText().toString();}
    public void requestKeyboard(){
        if(!failed && !stopRequested && game!=null){keyboardRequested=true;resumeView();}
    }
    public void requestStop(){
        if(stopRequested)return;
        stopRequested=true;pause();message.setText("Stopping session…");actions.requestStop();
    }

    /** Bind on the UI thread after the owner has started the real session off it. */
    public void bind(ClientPresentationSession value) throws IOException {
        uiThread();
        if (session != null || game != null) throw new IOException("A presentation session is already bound");
        if (value == null || !value.isReady() || failed || events.failure != null)
            throw new IOException("Presentation session is unavailable");
        GameInputView view = new GameInputView(getContext(), value.input(), value.surface(), new GameInputView.Events() {
            @Override public void failed(String reason) { events.failed(reason); }
            @Override public void cursorModeChanged(boolean enabled) {
                message.setText(enabled ? "Pointer controls · Y: camera" : "Camera controls · Y: pointer");
            }
            @Override public void rejected(String reason) { message.setText(reason); }
        });
        session = value; game = view;
        if (!foreground) game.pauseInput();
        viewport.addView(game, new FrameLayout.LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT, Gravity.CENTER));
        if (events.width > 0) frameSize(events.width, events.height);
        message.setText("Camera controls · Y: pointer");
        if (foreground && attached && hasWindowFocus()) resumeView(); else pauseView();
    }

    /** Activity.onStart/onResume forwards here; it does not create processes. */
    public void resume() { uiThread(); foreground = true; resumeView(); }
    /** Neutralize held input, detach rendering and mute audio immediately. */
    public void pause() { uiThread(); foreground = false; pauseView(); }
    private void resumeView() {
        if (!foreground || !attached || !hasWindowFocus() || failed || stopRequested || game == null) return;
        try {
            session.resumeInput();
            game.resumeInput(); game.requestFocus();
            if(keyboardRequested){keyboardRequested=false;game.showKeyboard();}
        } catch (IOException error) { events.failed("presentation-resume-failed"); }
    }
    private void pauseView() {
        if (game != null) { game.hideKeyboard(); game.pauseInput(); }
        if (session != null) try { session.pauseInput(); }
        catch (IOException error) { events.failed("presentation-pause-failed"); }
    }
    /** Detach a closed/replaced session; process shutdown remains with its owner. */
    public void unbind() {
        uiThread(); pauseView();
        if (game != null) viewport.removeView(game);
        game = null; session = null;
    }
    private void frameSize(int width, int height) {
        if (game != null && !failed) {
            game.frameSize(width, height);
            videoWidth = width; videoHeight = height; fitGame();
        }
    }
    /** Keep every game pixel visible and touchable across the available display. */
    private void fitGame() {
        if (game == null || videoWidth <= 0 || videoHeight <= 0 || viewport.getWidth() <= 0 || viewport.getHeight() <= 0) return;
        int width = viewport.getWidth();
        int height = Math.max(1, (int) ((long) width * videoHeight / videoWidth));
        if (height > viewport.getHeight()) {
            height = viewport.getHeight();
            width = Math.max(1, (int) ((long) height * videoWidth / videoHeight));
        }
        FrameLayout.LayoutParams params = (FrameLayout.LayoutParams) game.getLayoutParams();
        if (params.width != width || params.height != height) {
            params.width = width; params.height = height; params.gravity = Gravity.CENTER;
            game.setLayoutParams(params);
        }
    }
    private void showFailure() {
        failed = true; pauseView(); message.setText("Display or input stopped. Export the support bundle from the launcher.");
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow(); attached = true; events.attach(this); resumeView();
    }
    @Override protected void onDetachedFromWindow() {
        attached = false; pauseView(); events.detach(this); super.onDetachedFromWindow();
    }
    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) resumeView(); else pauseView();
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private static void uiThread() {
        if (Looper.myLooper() != Looper.getMainLooper()) throw new IllegalStateException("Presentation views require the UI thread");
    }
}
