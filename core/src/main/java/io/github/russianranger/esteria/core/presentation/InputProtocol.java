package io.github.russianranger.esteria.core.presentation;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Fixed 16-byte ESTRIN01 XTest request. No text, shell commands or arbitrary lengths. */
public final class InputProtocol {
    public static final byte[] GREETING = {'E','S','T','R','I','N','0','1'};
    private InputProtocol() {}
    public static byte[] packet(int type, int x, int y, int state) throws IOException {
        if (type < 0 || type > 3 || state < 0 || state > 31) throw new IOException("Invalid input event");
        if (type == 3) {
            if (state != 0 || x <= 0 || x > 0xffff || (y != 0 && y != 1))
                throw new IOException("Invalid key event");
        } else if (x < -4096 || x > 4096 || y < -4096 || y > 4096 || (type == 2 && (x != 0 || y != 0))) {
            throw new IOException("Input coordinates exceed protocol bounds");
        }
        return ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN).putInt(type).putInt(x).putInt(y).putInt(state).array();
    }
}
