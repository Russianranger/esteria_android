package io.github.russianranger.esteria.core.input;
import io.github.russianranger.esteria.core.presentation.InputSink;
import java.io.IOException;
import java.util.*;

public final class GameInputRouterTest {
    static final class Sink implements InputSink {
        final Set<Integer> keys = new HashSet<>(); final List<String> events = new ArrayList<>();
        int mask, dx, dy, x, y, releases;
        int acceptedSequences,lastSequenceLength;boolean rejectSequence;
        public void key(int key,boolean down){if(down)keys.add(key);else keys.remove(key);events.add(key+":"+down);}
        public void keySequence(int[] codes,boolean[] states)throws IOException{
            if(rejectSequence)throw new InputSink.BatchRejected("TEST_ONLY_QUEUE_REFUSAL");
            check(codes.length<=256,"Keyboard exceeded real transport batch limit");
            acceptedSequences++;lastSequenceLength=codes.length;
            for(int i=0;i<codes.length;i++)key(codes[i],states[i]);
        }
        public void pointer(int x,int y,int mask){this.x=x;this.y=y;this.mask=mask;}
        public void relativeMotion(int dx,int dy){this.dx+=dx;this.dy+=dy;}
        public void buttons(int mask){this.mask=mask;}
        public void releaseAll(){keys.clear();mask=0;releases++;}
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Sink sink=new Sink();GameInputRouter router=new GameInputRouter(sink);
        router.sticks(.3f,-.7f,0,0,0,0);check(sink.keys.containsAll(Arrays.asList((int)'w',(int)'e')),"forward and strafe");
        router.sticks(.2f,0,0,0,0,0);check(sink.keys.equals(Collections.singleton((int)'e')),"deadzone hysteresis");
        router.sticks(.1f,0,1,0,0,0);check(sink.keys.isEmpty()&&sink.mask==4,"camera holds right mouse");
        router.step(.02);check(sink.dx==20,"frame integrated camera motion");
        router.sticks(0,0,0,0,0,0);check(sink.mask==0,"neutral camera releases mouse");
        router.button(GameInputRouter.Button.Y,true);router.button(GameInputRouter.Button.Y,true);router.button(GameInputRouter.Button.Y,false);
        check(router.cursorMode(),"cursor toggle");router.button(GameInputRouter.Button.A,true);check(sink.mask==1,"cursor A clicks");
        router.touch(500,-5,400,200,800,400,true);check(sink.x==799&&sink.y==0,"touch coordinates clamp");
        router.button(GameInputRouter.Button.A,false);check(sink.mask==1,"touch retains its click source");
        router.touch(0,0,400,200,800,400,false);check(sink.mask==0,"all click sources release");
        router.sticks(0,-1,0,0,0,0);check(sink.keys.contains(0xff52),"cursor movement navigates menus");
        router.release();check(sink.keys.isEmpty()&&sink.mask==0,"focus loss neutralizes");
        sink.events.clear();KeyboardText.commit(sink,"Az!\n");
        check(sink.events.equals(Arrays.asList("65505:true","97:true","97:false","65505:false","122:true","122:false","65505:true","49:true","49:false","65505:false","65293:true","65293:false")),"shift and base-key text");
        int before=sink.events.size();try{KeyboardText.commit(sink,"valid☃");throw new AssertionError("Unicode silently accepted");}catch(IOException expected){}
        check(sink.events.size()==before,"unsupported commit sends no partial text");
        KeyboardText.Composition composition=new KeyboardText.Composition();
        sink.events.clear();check(composition.stage("ab"),"composition stages");composition.delete(sink,1);
        check(sink.events.isEmpty(),"composition backspace does not delete existing game text");
        composition.finish(sink);check(sink.events.equals(Arrays.asList("97:true","97:false")),"remaining draft commits");
        composition.finish(sink);check(sink.events.size()==2,"finish does not duplicate committed draft");
        sink.events.clear();composition.stage("go");composition.enter(sink);
        check(sink.events.equals(Arrays.asList("103:true","103:false","111:true","111:false","65293:true","65293:false")),"Enter preserves pending composition");
        sink.events.clear();composition.stage("ab");composition.delete(sink,3);composition.finish(sink);
        check(sink.events.equals(Arrays.asList("65288:true","65288:false")),"only deletion beyond staged draft reaches game");
        sink.events.clear();composition.stage("cancelled");composition.clear();composition.finish(sink);
        check(sink.events.isEmpty(),"discarded stale draft never commits");
        composition.stage("a".repeat(64));int batches=sink.acceptedSequences;composition.enter(sink);
        check(sink.events.size()==130&&sink.lastSequenceLength==130&&sink.acceptedSequences==batches+1,
                "64-character draft and Enter share one accepted atomic sequence");
        check(sink.events.subList(128,130).equals(Arrays.asList("65293:true","65293:false")),"Enter follows the complete draft");
        sink.events.clear();composition.stage("A".repeat(64));
        try{composition.enter(sink);throw new AssertionError("over-limit input event batch accepted");}catch(KeyboardText.RejectedText expected){}
        check(sink.events.isEmpty(),"rejected shifted draft and Enter send no partial text");composition.finish(sink);
        check(sink.events.size()==256,"event-cap refusal preserves editable draft without changing64textlimit");
        sink.events.clear();KeyboardText.Composition editor=new KeyboardText.Composition();editor.stage("go");editor.submit(sink);
        check(sink.events.equals(Arrays.asList("103:true","103:false","111:true","111:false","65293:true","65293:false"))&&!editor.isOpen(),
                "editor Done submits pending text then Enter and closes its connection");
        before=sink.events.size();
        try{editor.submit(sink);throw new AssertionError("late action/key event submitted twice");}catch(KeyboardText.RejectedText expected){}
        check(sink.events.size()==before&&!editor.stage("late"),"closed connection cannot repeat an editor submission");
        sink.events.clear();editor=new KeyboardText.Composition();editor.commit(sink,"ok");sink.events.clear();editor.submit(sink);
        check(sink.events.equals(Arrays.asList("65293:true","65293:false")),"editor Done sends Enter for already committed IME text without duplicating it");
        sink.events.clear();editor=new KeyboardText.Composition();editor.stage("retry");sink.rejectSequence=true;
        try{editor.submit(sink);throw new AssertionError("queue refusal was hidden");}catch(IOException expected){}
        check(editor.isOpen()&&sink.events.isEmpty(),"queue refusal preserves the editable draft and sends no events");sink.rejectSequence=false;
        editor.submit(sink);check(sink.events.size()==12&&sink.events.get(10).equals("65293:true"),"retry sends the complete retained draft and one Enter");
        sink.events.clear();editor=new KeyboardText.Composition();editor.stage("cancelled on Back or pause");editor.invalidate();
        try{editor.submit(sink);throw new AssertionError("cancelled keyboard submitted");}catch(KeyboardText.RejectedText expected){}
        try{editor.commit(sink,"late callback");throw new AssertionError("invalidated keyboard committed");}catch(KeyboardText.RejectedText expected){}
        check(sink.events.isEmpty()&&!editor.stage("late"),"hidden/lifecycle-invalidated keyboard discards draft and rejects late callbacks");
        editor=new KeyboardText.Composition();editor.stage("new");editor.submit(sink);
        check(sink.events.size()==8&&sink.events.get(0).equals("110:true"),"new connection does not inherit a cancelled draft");
        try{router.sticks(Float.NaN,0,0,0,0,0);throw new AssertionError("NaN accepted");}catch(IOException expected){}
        System.out.println("Controller/keyboard: movement, camera, mode, touch ownership, neutralization, ASCII/composition, atomic editor submission, queue refusal and late-callback checks passed");
    }
}
