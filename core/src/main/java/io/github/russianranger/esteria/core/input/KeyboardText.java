package io.github.russianranger.esteria.core.input;

import io.github.russianranger.esteria.core.presentation.InputSink;
import java.io.IOException;

/** Physical US keyboard fallback for login/chat; unsupported Unicode fails explicitly. */
public final class KeyboardText {
    private static final String SHIFTED = "~!@#$%^&*()_+{}|:\"<>?";
    private static final String BASE = "`1234567890-=[]\\;',./";
    public static final class RejectedText extends IOException {
        private static final long serialVersionUID = 1L;
        public RejectedText(String message) { super(message); }
    }
    private KeyboardText() {}
    public static void commit(InputSink sink, CharSequence text) throws IOException {
        send(sink,text,false);
    }
    private static void send(InputSink sink,CharSequence text,boolean appendEnter)throws IOException {
        if (text == null || text.length() > 64) throw new RejectedText("Keyboard text exceeds the supported input limit");
        // Validate the whole commit first; never send a partially supported password/string.
        for (int i = 0; i < text.length(); i++) {
            char value = text.charAt(i);
            if ((value < 32 || value > 126) && value != '\n' && value != '\t')
                throw new RejectedText("This keyboard bridge currently supports printable ASCII, Tab and Enter");
        }
        int[] codes = new int[text.length() * 4 + (appendEnter ? 2 : 0)];
        boolean[] states = new boolean[codes.length]; int used = 0;
        for (int i = 0; i < text.length(); i++) {
            char value = text.charAt(i); int key = value;
            boolean shift = value >= 'A' && value <= 'Z';
            if (shift) key = value + ('a' - 'A');
            int index = SHIFTED.indexOf(value);
            if (index >= 0) { shift = true; key = BASE.charAt(index); }
            if (value == '\n') key = 0xff0d;
            if (value == '\t') key = 0xff09;
            if (shift) { codes[used] = 0xffe1; states[used++] = true; }
            codes[used] = key; states[used++] = true;
            codes[used] = key; states[used++] = false;
            if (shift) { codes[used] = 0xffe1; states[used++] = false; }
        }
        if(appendEnter){codes[used]=0xff0d;states[used++]=true;codes[used]=0xff0d;states[used++]=false;}
        if(used>256)throw new RejectedText("Shorten the text before submitting");
        if (used != 0) sink.keySequence(java.util.Arrays.copyOf(codes, used), java.util.Arrays.copyOf(states, used));
    }
    public static void backspace(InputSink sink, int count) throws IOException {
        if (count < 0 || count > 64) throw new RejectedText("Keyboard deletion exceeds the supported limit");
        int[] codes = new int[count * 2]; boolean[] states = new boolean[codes.length];
        for (int i = 0; i < codes.length; i++) { codes[i] = 0xff08; states[i] = i % 2 == 0; }
        if (count != 0) sink.keySequence(codes, states);
    }
    /** IME composition is local until explicitly committed; no draft text reaches the guest. */
    public static final class Composition {
        private String pending = "";
        private boolean closed;
        public void clear() { pending = ""; }
        /** A hidden/stale input connection may never submit a later callback. */
        public void invalidate() { clear();closed=true; }
        public boolean isOpen() { return !closed; }
        private void checkOpen()throws RejectedText {if(closed)throw new RejectedText("This keyboard connection is closed");}
        public boolean stage(CharSequence text) {
            if (closed || text == null || text.length() > 64) return false;
            pending = text.toString(); return true;
        }
        public void commit(InputSink sink, CharSequence text) throws IOException {
            checkOpen();
            KeyboardText.commit(sink, text); pending = "";
        }
        public void finish(InputSink sink) throws IOException {
            checkOpen();
            if (!pending.isEmpty()) commit(sink, pending);
        }
        public void delete(InputSink sink, int before) throws IOException {
            checkOpen();
            if (before < 0 || before > 64) throw new RejectedText("Keyboard deletion exceeds the supported limit");
            if (!pending.isEmpty()) {
                // The staged composition has not reached the game. Delete it locally first.
                int removed = Math.min(before, pending.length());
                String retained = pending.substring(0, pending.length() - removed);
                if (before > removed) KeyboardText.backspace(sink, before - removed);
                pending = retained;
            } else KeyboardText.backspace(sink, before);
        }
        public void enter(InputSink sink) throws IOException { checkOpen();send(sink,pending,true);pending=""; }
        /** One accepted editor submission closes this connection. Queue failure
         * preserves both the draft and its ability to be retried. */
        public void submit(InputSink sink)throws IOException {enter(sink);closed=true;}
    }
}
