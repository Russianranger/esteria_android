package io.github.russianranger.esteria.core.input;

import io.github.russianranger.esteria.core.presentation.InputSink;
import java.io.IOException;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.Set;

/** Initial keyboard/mouse controller profile. Confined to the presentation UI thread. */
public final class GameInputRouter {
    public enum Button { A, B, X, Y, LB, RB, START, SELECT, L3, R3, UP, DOWN, LEFT, RIGHT, LT, RT }
    private static final int ESC = 0xff1b, TAB = 0xff09, UP = 0xff52, DOWN = 0xff54,
            LEFT = 0xff51, RIGHT = 0xff53;
    private final InputSink sink;
    private final EnumSet<Button> held = EnumSet.noneOf(Button.class);
    private final Set<Integer> keys = new HashSet<>();
    private boolean cursorMode, forward, backward, left, right, leftTrigger, rightTrigger;
    private boolean hatUp, hatDown, hatLeft, hatRight;
    private float cameraX, cameraY;
    private double remainderX, remainderY;
    private int mouseMask, touchMask;
    public GameInputRouter(InputSink sink) {
        if (sink == null) throw new IllegalArgumentException("A connected input sink is required");
        this.sink = sink;
    }
    public boolean cursorMode() { return cursorMode; }
    public void button(Button button, boolean down) throws IOException {
        boolean changed = down ? held.add(button) : held.remove(button);
        if (!changed) return;
        if (button == Button.Y && down) {
            boolean next = !cursorMode;
            release(); cursorMode = next; held.add(Button.Y);
        }
        updateKeys(); updateButtons();
    }
    /** Android axes are normalized by the adapter before reaching this method. */
    public void sticks(float moveX, float moveY, float lookX, float lookY, float triggerL, float triggerR) throws IOException {
        for (float value : new float[]{moveX, moveY, lookX, lookY, triggerL, triggerR})
            if (!Float.isFinite(value) || value < -1 || value > 1) throw new IOException("Invalid controller axis");
        forward = active(-moveY, forward); backward = active(moveY, backward);
        left = active(-moveX, left); right = active(moveX, right);
        cameraX = curve(lookX); cameraY = curve(lookY);
        leftTrigger = triggerL >= (leftTrigger ? .35f : .55f);
        rightTrigger = triggerR >= (rightTrigger ? .35f : .55f);
        updateKeys(); updateButtons();
    }
    public void hat(float x,float y)throws IOException{
        if(!Float.isFinite(x)||!Float.isFinite(y)||Math.abs(x)>1||Math.abs(y)>1)throw new IOException("Invalid controller hat");
        hatUp=y<-.5f;hatDown=y>.5f;hatLeft=x<-.5f;hatRight=x>.5f;updateKeys();
    }
    private static boolean active(float value, boolean previous) { return value >= (previous ? .15f : .25f); }
    private static float curve(float value) {
        float magnitude = Math.abs(value);
        if (magnitude <= .20f) return 0;
        float normalized = (magnitude - .20f) / .80f;
        return Math.copySign(normalized * normalized, value);
    }
    /** Frame-time integration prevents event frequency from changing camera speed. */
    public void step(double elapsedSeconds) throws IOException {
        if (!Double.isFinite(elapsedSeconds) || elapsedSeconds < 0) throw new IOException("Invalid input elapsed time");
        double delta = Math.min(.05, elapsedSeconds), speed = cursorMode ? 700 : 1000;
        remainderX += cameraX * delta * speed; remainderY += cameraY * delta * speed;
        int dx = (int)remainderX, dy = (int)remainderY;
        remainderX -= dx; remainderY -= dy;
        if (dx != 0 || dy != 0) sink.relativeMotion(dx, dy);
    }
    private void updateKeys() throws IOException {
        Set<Integer> next = new HashSet<>();
        if (forward) next.add(cursorMode ? UP : (int)'w');
        if (backward) next.add(cursorMode ? DOWN : (int)'s');
        if (left) next.add(cursorMode ? LEFT : (int)'q');
        if (right) next.add(cursorMode ? RIGHT : (int)'e');
        if(hatUp)next.add(binding(Button.UP,cursorMode));
        if(hatDown)next.add(binding(Button.DOWN,cursorMode));
        if(hatLeft)next.add(binding(Button.LEFT,cursorMode));
        if(hatRight)next.add(binding(Button.RIGHT,cursorMode));
        for (Button button : held) {
            int key = binding(button, cursorMode);
            if (key != 0) next.add(key);
        }
        for (int key : new HashSet<>(keys)) if (!next.contains(key)) { sink.key(key, false); keys.remove(key); }
        for (int key : next) if (!keys.contains(key)) { sink.key(key, true); keys.add(key); }
    }
    private static int binding(Button button, boolean cursor) {
        switch (button) {
            case A: return cursor ? 0 : ' ';
            case B: return cursor ? ESC : '1';
            case X: return 'b';
            case LB: return TAB;
            case RB: return cursor ? 0xff0d : '2';
            case START: return ESC;
            case SELECT: return 'm';
            case L3: return 'j';
            case R3: return 'c';
            case UP: return cursor ? UP : '3';
            case RIGHT: return cursor ? RIGHT : '4';
            case DOWN: return cursor ? DOWN : '5';
            case LEFT: return cursor ? LEFT : '6';
            default: return 0;
        }
    }
    private int desiredButtons() {
        int next = touchMask;
        if (leftTrigger || held.contains(Button.LT) || (cursorMode && held.contains(Button.A))) next |= 1;
        if (rightTrigger || held.contains(Button.RT) || (!cursorMode && (cameraX != 0 || cameraY != 0))) next |= 4;
        return next;
    }
    private void updateButtons() throws IOException {
        int next = desiredButtons();
        if (next != mouseMask) { sink.buttons(next); mouseMask = next; }
    }
    /** Coordinate conversion is independent of controller camera mode. */
    public void touch(float x, float y, int viewWidth, int viewHeight, int frameWidth, int frameHeight, boolean down) throws IOException {
        if (!Float.isFinite(x) || !Float.isFinite(y) || viewWidth <= 0 || viewHeight <= 0 || frameWidth <= 0 || frameHeight <= 0)
            throw new IOException("Presentation geometry is unavailable");
        int px = Math.max(0, Math.min(frameWidth - 1, (int)(x * frameWidth / viewWidth)));
        int py = Math.max(0, Math.min(frameHeight - 1, (int)(y * frameHeight / viewHeight)));
        touchMask = down ? 1 : 0;
        int next = desiredButtons();
        sink.pointer(px, py, next); mouseMask = next;
    }
    /** Call on focus loss, controller removal, cancellation, pause and shutdown. */
    public void release() throws IOException {
        held.clear(); keys.clear(); forward = backward = left = right = leftTrigger = rightTrigger = false;
        hatUp=hatDown=hatLeft=hatRight=false;
        cameraX = cameraY = 0; remainderX = remainderY = 0; mouseMask = touchMask = 0;
        sink.releaseAll();
    }
}
