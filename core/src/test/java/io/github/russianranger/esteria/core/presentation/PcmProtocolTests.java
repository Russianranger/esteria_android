package io.github.russianranger.esteria.core.presentation;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

public final class PcmProtocolTests {
    private static int groups;
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static final class Sink implements PcmProtocol.Sink {
        int capacity, starts, stops, resets, writes, closes, accepted = 8;
        byte[] heard;
        public void configure(int frames) { capacity = frames; }
        public void start() { starts++; }
        public void stop() { stops++; }
        public void reset() { resets++; }
        public int playbackHead() { return 0x80000005; }
        public int write(byte[] bytes, int length) { writes++; heard = Arrays.copyOf(bytes, length); return accepted; }
        public void close() { closes++; }
    }
    private static byte[] words(int... words) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        for (int word : words) out.writeInt(Integer.reverseBytes(word));
        return bytes.toByteArray();
    }
    private static byte[] join(byte[]... parts) throws IOException {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        for (byte[] part : parts) result.write(part);
        return result.toByteArray();
    }
    private static byte[] header(int capacity) throws IOException { return words(PcmProtocol.MAGIC, 1, 48000, 2, capacity); }
    private static void reject(byte[] bytes, Sink sink) throws IOException {
        try { new PcmProtocol().run(new ByteArrayInputStream(bytes), new ByteArrayOutputStream(), sink); }
        catch (IOException expected) { check(sink.closes == 1); return; }
        throw new AssertionError("Malformed stream accepted");
    }
    public static void main(String[] args) throws Exception {
        byte[] pcm = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
        Sink sink = new Sink(); ByteArrayOutputStream replies = new ByteArrayOutputStream();
        byte[] commands = join(header(1920), words(1, 4, 4), pcm, words(3, 2, 5));
        InputStream fragmented = new FilterInputStream(new ByteArrayInputStream(commands)) {
            @Override public int read(byte[] bytes, int offset, int length) throws IOException {
                return super.read(bytes, offset, Math.min(length, 1));
            }
        };
        PcmProtocol protocol = new PcmProtocol(); protocol.run(fragmented, replies, sink);
        check(sink.capacity == 1920 && sink.starts == 1 && sink.stops == 1 && sink.resets == 1 && sink.closes == 1);
        check(Arrays.equals(pcm, sink.heard)); check(protocol.acceptedFrames() == 2);
        check(Arrays.equals(replies.toByteArray(), words(0,0,2,0x80000005,0,0))); groups++;

        sink = new Sink(); sink.accepted = 0; replies.reset();
        protocol = new PcmProtocol(); protocol.run(new ByteArrayInputStream(join(header(64), words(4,4),pcm)), replies, sink);
        check(protocol.acceptedFrames() == 0 && sink.writes == 1 && Arrays.equals(replies.toByteArray(), words(0,0))); groups++;

        for (int capacity : new int[]{0,63,48001,Integer.MAX_VALUE}) {
            Sink invalid = new Sink(); reject(header(capacity), invalid); check(invalid.capacity == 0);
        }
        for (int[] identity : new int[][]{{0,1,48000,2,64},{PcmProtocol.MAGIC,2,48000,2,64},
                {PcmProtocol.MAGIC,1,44100,2,64},{PcmProtocol.MAGIC,1,48000,1,64}})
            reject(words(identity), new Sink());
        groups++;

        for (int count : new int[]{-1,0,4097,Integer.MAX_VALUE}) {
            Sink invalid = new Sink(); reject(join(header(64),words(4,count)), invalid); check(invalid.writes == 0);
        }
        for (int accepted : new int[]{-1,1,6,20}) {
            Sink invalid = new Sink(); invalid.accepted = accepted; reject(join(header(64),words(4,4),pcm), invalid);
        }
        reject(join(header(64),words(99)),new Sink()); groups++;

        // Every partial header, command word and PCM frame fails rather than looking like clean EOF.
        for (int length = 0; length < 20; ++length) reject(Arrays.copyOf(header(64),length),new Sink());
        for (int length = 1; length < 4; ++length)
            reject(join(header(64),Arrays.copyOf(words(1),length)),new Sink());
        for (int length = 0; length < 16; ++length)
            reject(join(header(64),words(4,4),Arrays.copyOf(pcm,length)),new Sink());
        sink = new Sink(); new PcmProtocol().run(new ByteArrayInputStream(header(64)),new ByteArrayOutputStream(),sink);
        check(sink.closes == 1 && sink.writes == 0); groups++;

        byte[] packet = InputProtocol.packet(1,-17,23,5);
        ByteBuffer input = ByteBuffer.wrap(packet).order(ByteOrder.BIG_ENDIAN);
        check(input.getInt() == 1 && input.getInt() == -17 && input.getInt() == 23 && input.getInt() == 5);
        check(InputProtocol.packet(3,0xffe1,1,0).length == 16);
        for (int[] invalid : new int[][]{{4,0,0,0},{1,4097,0,0},{2,1,0,0},{0,0,0,32},{3,0,1,0},
                {3,0xffe1,2,0},{3,0xffe1,1,1},{3,0x01110000,1,0}}) {
            try { InputProtocol.packet(invalid[0],invalid[1],invalid[2],invalid[3]); throw new AssertionError(); }
            catch (IOException expected) { /* Correct fixed protocol rejection. */ }
        }
        groups++;
        System.out.println("Presentation protocol groups passed: " + groups);
    }
}
