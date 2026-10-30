package android.os;

/** Host lifecycle fixture only. Android's real Looper is used in every APK. */
public final class Looper {
    private static final Looper MAIN=new Looper();
    private Looper() { }
    public static Looper getMainLooper(){return MAIN;}
    public static Looper myLooper(){return null;}
}
