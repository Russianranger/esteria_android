package io.github.russianranger.esteria.core.presentation;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Authenticated private X11 component commands. Does not launch a game or select a GPU. */
public final class X11SessionPlan {
    private X11SessionPlan() { }
    public static void checkDisplay(int display) {
        if (display<64 || display>16383) throw new IllegalArgumentException("Private X11 display is outside supported range");
    }
    /** Xauthority uses network byte order, FamilyWild, and an exact display number. */
    public static byte[] authority(int display,byte[] cookie) throws IOException {
        checkDisplay(display);
        if (cookie==null || cookie.length!=16) throw new IllegalArgumentException("X11 requires a 16-byte random cookie");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try (DataOutputStream out=new DataOutputStream(bytes)) {
            out.writeShort(65535); field(out,new byte[0]);
            field(out,Integer.toString(display).getBytes(StandardCharsets.US_ASCII));
            field(out,"MIT-MAGIC-COOKIE-1".getBytes(StandardCharsets.US_ASCII));field(out,cookie);
        }
        return bytes.toByteArray();
    }
    private static void field(DataOutputStream out,byte[] bytes) throws IOException { out.writeShort(bytes.length);out.write(bytes); }
    public static List<String> server(int display) {
        checkDisplay(display);
        return Arrays.asList("/usr/bin/Xtigervnc",":"+display,"-geometry","1280x720","-depth","24",
                "-nolisten","tcp","-rfbport","-1","-auth","/session/Xauthority","-noreset");
    }
    public static List<String> frame() { return Arrays.asList("/esteria-bridges/bin/esteria-x11-frame","/session/frame.sock","30"); }
    public static List<String> input() { return Arrays.asList("/esteria-bridges/bin/esteria-x11-input","/session/input.sock"); }
    public static Map<String,String> environment(int display) {
        checkDisplay(display);
        return Map.of("DISPLAY",":"+display,"XAUTHORITY","/session/Xauthority",
                "ESTERIA_AUDIO_SOCKET","/session/audio.sock",
                "ALSA_CONFIG_PATH","/esteria-bridges/etc/alsa-esteria.conf",
                "WINEDLLOVERRIDES","winepulse.drv=","WINEESYNC","0","WINEFSYNC","0");
    }
}
