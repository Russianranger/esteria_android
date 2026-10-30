package io.github.russianranger.esteria.presentation;

import io.github.russianranger.esteria.core.input.KeyboardText;
import io.github.russianranger.esteria.core.presentation.InputSink;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;

/** Executes the actual InputBridge batch/held-state policy with no writer or
 * socket transport. A task-only LocalSocket stub refuses all actual I/O. */
public final class InputBatchReservationTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Object field(InputBridge bridge,String name)throws Exception {
        Field field=InputBridge.class.getDeclaredField(name);field.setAccessible(true);return field.get(bridge);
    }
    @SuppressWarnings("unchecked") private static ArrayDeque<byte[]> pending(InputBridge bridge)throws Exception {
        return (ArrayDeque<byte[]>)field(bridge,"pending");
    }
    private static List<byte[]> snapshot(InputBridge bridge)throws Exception {
        List<byte[]> result=new ArrayList<>();for(byte[] event:pending(bridge))result.add(event.clone());return result;
    }
    private static void same(List<byte[]> expected,InputBridge bridge)throws Exception {
        List<byte[]> actual=snapshot(bridge);check(actual.size()==expected.size(),"Rejected batch changed queue length");
        for(int i=0;i<actual.size();i++)check(Arrays.equals(expected.get(i),actual.get(i)),"Rejected batch changed earlier queued bytes");
    }
    private static void fill(InputBridge bridge,int count)throws IOException {
        int[] keys=new int[count];boolean[] states=new boolean[count];Arrays.fill(keys,'a');
        for(int i=0;i<count;i++)states[i]=i%2==0;
        bridge.keySequence(keys,states);
    }
    public static void main(String[] args)throws Exception {
        Constructor<InputBridge> constructor=InputBridge.class.getDeclaredConstructor(InputBridge.Events.class);constructor.setAccessible(true);
        try(InputBridge bridge=constructor.newInstance((Object)null)) {
            bridge.key('w',true);bridge.buttons(4);fill(bridge,254);
            check(pending(bridge).size()==256,"Fixture did not fill real queue");
            List<byte[]> before=snapshot(bridge);Object held=Set.copyOf((Set<?>)field(bridge,"keys"));Object mouse=field(bridge,"buttonMask");
            try{bridge.keySequence(new int[]{0},new boolean[]{true});throw new AssertionError("Malformed event accepted while queue full");}
            catch(InputSink.BatchRejected unsafe){throw new AssertionError("Malformed event mislabeled retryable while queue full",unsafe);}
            catch(IOException expectedFailure){ }
            same(before,bridge);
            KeyboardText.Composition editor=new KeyboardText.Composition();editor.stage("retry");
            try{editor.submit(bridge);throw new AssertionError("Full queue accepted an editor batch");}
            catch(InputSink.BatchRejected expected){ }
            same(before,bridge);check(!(boolean)field(bridge,"closed")&&held.equals(field(bridge,"keys"))&&mouse.equals(field(bridge,"buttonMask")),
                    "Whole-batch capacity refusal changed input ownership or disconnected");
            check(editor.isOpen(),"Whole-batch refusal closed the editable connection");
            // Model writer progress only: this fixture does not claim socket ACKs.
            pending(bridge).clear();editor.submit(bridge);
            check(!editor.isOpen()&&pending(bridge).size()==12,"Exact retained draft was not accepted on retry");
            int index=0;String expected="retry\n";
            for(byte[] raw:pending(bridge)) {
                ByteBuffer event=ByteBuffer.wrap(raw).order(ByteOrder.BIG_ENDIAN);int key=expected.charAt(index/2);if(key=='\n')key=0xff0d;
                check(event.getInt()==3&&event.getInt()==key&&event.getInt()==(index%2==0?1:0)&&event.getInt()==0,
                        "Retried batch changed text/Enter order or key-up");index++;
            }
            pending(bridge).clear();
            try{bridge.keySequence(new int[257],new boolean[257]);throw new AssertionError("Malformed batch accepted");}
            catch(InputSink.BatchRejected unsafe){throw new AssertionError("Malformed input mislabeled retryable",unsafe);}
            catch(IOException expectedFailure){ }
            fill(bridge,256);
            try{bridge.key('z',true);throw new AssertionError("Individual key overflow accepted");}
            catch(InputSink.BatchRejected unsafe){throw new AssertionError("Individual input overflow mislabeled retryable",unsafe);}
            catch(IOException expectedFailure){ }
            check((boolean)field(bridge,"closed")&&pending(bridge).isEmpty(),"Ambiguous individual overflow must disconnect as before");
            try{bridge.keySequence(new int[0],new boolean[0]);throw new AssertionError("Closed transport accepted batch");}
            catch(InputSink.BatchRejected unsafe){throw new AssertionError("Closed transport mislabeled retryable",unsafe);}
            catch(IOException expectedFailure){ }
        }
        System.out.println("Actual InputBridge: atomic full-queue refusal, unchanged held state, exact draft retry and fatal individual/closed guards passed; no socket or X11 execution");
    }
}
