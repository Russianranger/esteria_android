package io.github.russianranger.esteria.presentation;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.SystemClock;
import android.system.Os;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.MainActivity;
import io.github.russianranger.esteria.core.presentation.InputSink;
import io.github.russianranger.esteria.input.GameInputView;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real Android widget/IME/event callbacks, with a bounded Java-only input sink.
 * The frame producer is synthetic; no game, Wine, X11 or physical controller runs.
 */
@RunWith(AndroidJUnit4.class)
@android.annotation.TargetApi(33)
public final class GameInputAndroidTest {
    private static final int ENTER=0xff0d, SHIFT=0xffe1, CAPACITY=256, FIXED_KEY_EVENT_DEVICE=0x4553;
    private final Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
    private <T> T ui(Callable<T> call) {
        AtomicReference<T> result=new AtomicReference<>(); AtomicReference<Throwable> failure=new AtomicReference<>();
        instrumentation.runOnMainSync(()->{try{result.set(call.call());}catch(Throwable error){failure.set(error);}});
        if(failure.get()!=null)throw new AssertionError("Android UI assertion failed",failure.get());
        return result.get();
    }
    private void waitFor(Callable<Boolean> condition,String reason)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
        while(!condition.call()&&System.nanoTime()<deadline)Thread.sleep(20);
        assertTrue(reason,condition.call());
    }

    /** This models bounded acceptance only, not InputBridge socket ACKs. */
    private static final class RecordingSink implements InputSink {
        final List<String> queue=new ArrayList<>(); final Set<Integer> held=new HashSet<>();
        int mask,releases,batches,batchRefusals,pointers,relativeCalls,dx,dy;
        int pointerX=-1,pointerY=-1;
        private void room(int count)throws IOException {
            if(count<0||queue.size()+count>CAPACITY)throw new IOException("Recording sink individual capacity exceeded");
        }
        public void key(int key,boolean down)throws IOException {
            room(1);queue.add(key+":"+down);if(down)held.add(key);else held.remove(key);
        }
        public void keySequence(int[] keys,boolean[] down)throws IOException {
            if(keys.length!=down.length||keys.length>CAPACITY)throw new IOException("Invalid recording batch");
            if(queue.size()+keys.length>CAPACITY){batchRefusals++;throw new BatchRejected("Input queue is full; retry the text");}
            for(int i=0;i<keys.length;i++)key(keys[i],down[i]);batches++;
        }
        public void pointer(int x,int y,int buttons){pointerX=x;pointerY=y;mask=buttons;pointers++;}
        public void relativeMotion(int x,int y){dx+=x;dy+=y;relativeCalls++;}
        public void buttons(int buttons){mask=buttons;}
        public void releaseAll(){held.clear();mask=0;releases++;}
        void occupy()throws IOException {assertTrue(queue.isEmpty());for(int i=0;i<CAPACITY;i++)key('a',i%2==0);}
        void drain(){queue.clear();}
        void exact(int... codes) {
            List<String> expected=new ArrayList<>();for(int i=0;i<codes.length;i++)expected.add(codes[i]+":"+(i%2==0));
            assertEquals(expected,queue);assertTrue("Accepted keyboard batches must release every key",held.isEmpty());
        }
    }

    private static boolean imeVisible(GameInputView view) {
        WindowInsets insets=view.getRootWindowInsets();return insets!=null&&insets.isVisible(WindowInsets.Type.ime());
    }
    private void tap(Button button)throws Exception {
        instrumentation.waitForIdleSync();
        int[] point=ui(()->{int[] p=new int[2];button.getLocationOnScreen(p);p[0]+=button.getWidth()/2;p[1]+=button.getHeight()/2;return p;});
        long now=SystemClock.uptimeMillis();
        for(int action:new int[]{MotionEvent.ACTION_DOWN,MotionEvent.ACTION_UP}) {
            MotionEvent event=MotionEvent.obtain(now,SystemClock.uptimeMillis(),action,point[0],point[1],0);
            event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
            try{instrumentation.sendPointerSync(event);}finally{event.recycle();}
        }
        instrumentation.waitForIdleSync();
    }
    private InputConnection open(Button keyboard,GameInputView view)throws Exception {
        tap(keyboard);
        waitFor(()->ui(()->imeVisible(view)&&view.hasFocus()&&
                ((InputMethodManager)view.getContext().getSystemService(Context.INPUT_METHOD_SERVICE)).isActive(view)),
                "A real software keyboard must become visible for the attached game widget");
        return ui(()->{
            EditorInfo info=new EditorInfo();InputConnection connection=view.onCreateInputConnection(info);
            assertEquals(EditorInfo.IME_ACTION_DONE,info.imeOptions&EditorInfo.IME_MASK_ACTION);
            assertTrue((info.imeOptions&EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING)!=0);
            assertNotNull(connection);return connection;
        });
    }
    private void hidden(GameInputView view)throws Exception {
        waitFor(()->ui(()->!imeVisible(view)),"Accepted editor submission or Back must hide the real software keyboard");
    }
    private static KeyEvent key(int action,int code) {
        long now=SystemClock.uptimeMillis();return new KeyEvent(now,now,action,code,0,0,FIXED_KEY_EVENT_DEVICE,0,0,InputDevice.SOURCE_GAMEPAD);
    }
    private void touch(GameInputView view,int action,float x,float y) {
        ui(()->{
            long now=SystemClock.uptimeMillis();MotionEvent event=MotionEvent.obtain(now,now,action,x,y,0);
            event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
            try{assertTrue(view.dispatchTouchEvent(event));}finally{event.recycle();}return null;
        });
    }
    private void sticks(GameInputView view,int deviceId,float moveX,float moveY,float lookX,float lookY) {
        ui(()->{
            MotionEvent.PointerProperties pointer=new MotionEvent.PointerProperties();pointer.id=0;
            MotionEvent.PointerCoords axes=new MotionEvent.PointerCoords();
            axes.setAxisValue(MotionEvent.AXIS_X,moveX);axes.setAxisValue(MotionEvent.AXIS_Y,moveY);
            axes.setAxisValue(MotionEvent.AXIS_Z,lookX);axes.setAxisValue(MotionEvent.AXIS_RZ,lookY);
            long now=SystemClock.uptimeMillis();
            MotionEvent event=MotionEvent.obtain(now,now,MotionEvent.ACTION_MOVE,1,
                    new MotionEvent.PointerProperties[]{pointer},new MotionEvent.PointerCoords[]{axes},
                    0,0,1,1,deviceId,0,InputDevice.SOURCE_JOYSTICK,0);
            try{assertTrue(view.dispatchGenericMotionEvent(event));}finally{event.recycle();}return null;
        });
    }

    @Test public void actualImeTouchAndControllerCallbacks()throws Exception {
        Context context=instrumentation.getTargetContext();
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        assertTrue(BuildConfig.PRESENTATION_EMULATOR_TEST);assertFalse(BuildConfig.PROOT_PACKAGED);
        Path root=Files.createTempDirectory(context.getFilesDir().toPath(),"input-widget-");Os.chmod(root.toString(),0700);
        Activity activity=instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        AtomicReference<GameInputView> view=new AtomicReference<>();AtomicReference<Button> keyboard=new AtomicReference<>();
        AtomicReference<LinearLayout> fixture=new AtomicReference<>();AtomicReference<String> failure=new AtomicReference<>();
        AtomicInteger rejections=new AtomicInteger(),modeChanges=new AtomicInteger(),frameUpdates=new AtomicInteger();RecordingSink sink=new RecordingSink();
        try(PresentationAudioTest.Frames frames=new PresentationAudioTest.Frames(root,false);
            SurfaceBridge bridge=new SurfaceBridge(context,root.toFile(),new SurfaceBridge.Events(){
                public void frameSize(int width,int height){view.get().frameSize(width,height);frameUpdates.incrementAndGet();}
                public void failed(String reason){failure.set(reason);}
            })) {
            try {
                ui(()->{
                    LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.VERTICAL);fixture.set(box);
                    GameInputView display=new GameInputView(activity,sink,bridge,new GameInputView.Events(){
                        public void failed(String reason){failure.set(reason);}
                        public void rejected(String reason){rejections.incrementAndGet();}
                        public void cursorModeChanged(boolean enabled){modeChanges.incrementAndGet();}
                    });view.set(display);
                    Button button=new Button(activity);button.setText("Keyboard");button.setOnClickListener(v->display.showKeyboard());keyboard.set(button);
                    // Keep the fixture's injected touch outside the IME window
                    // while hide/show resizes the Surface below this toolbar.
                    box.addView(button,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));
                    box.addView(display,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
                    ((ViewGroup)activity.findViewById(android.R.id.content)).addView(box,new FrameLayout.LayoutParams(-1,-1));
                    display.requestFocus();return null;
                });
                waitFor(()->frameUpdates.get()>0&&ui(()->view.get().hasWindowFocus()&&view.get().getWidth()>0),
                        "The real Surface must receive a frame before input is admitted");
                GameInputView display=view.get();Button button=keyboard.get();

                InputConnection done=open(button,display);
                ui(()->{sink.drain();assertTrue(done.setComposingText("Ab",1));assertTrue(sink.queue.isEmpty());
                    assertFalse(done.performEditorAction(EditorInfo.IME_ACTION_SEARCH));
                    assertTrue(done.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    // Shift has independent press/release ownership around A.
                    assertEquals(List.of(SHIFT+":true","97:true","97:false",SHIFT+":false","98:true","98:false",ENTER+":true",ENTER+":false"),sink.queue);
                    assertTrue(sink.held.isEmpty());int accepted=sink.queue.size();
                    assertFalse(done.performEditorAction(EditorInfo.IME_ACTION_DONE));assertFalse(done.commitText("duplicate",1));
                    assertEquals(accepted,sink.queue.size());return null;
                });hidden(display);

                InputConnection retry=open(button,display);
                ui(()->{sink.drain();assertTrue(retry.setComposingText("retry",1));sink.occupy();List<String> before=List.copyOf(sink.queue);
                    Set<Integer> held=Set.copyOf(sink.held);int rejected=rejections.get();
                    assertFalse(retry.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    assertEquals(before,sink.queue);assertEquals(held,sink.held);assertEquals(rejected+1,rejections.get());
                    assertTrue(imeVisible(display));assertNull(failure.get());
                    // Explicit fixture-consumer progress; no transport ACK is claimed.
                    sink.drain();assertTrue(retry.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    sink.exact('r','r','e','e','t','t','r','r','y','y',ENTER,ENTER);return null;
                });hidden(display);

                InputConnection stale=open(button,display);
                ui(()->{sink.drain();assertTrue(stale.setComposingText("stale",1));
                    InputConnection replacement=display.onCreateInputConnection(new EditorInfo());
                    assertFalse(stale.commitText("late",1));assertFalse(stale.finishComposingText());
                    assertFalse(stale.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    assertFalse(stale.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_ENTER)));
                    assertTrue(replacement.setComposingText("closed",1));replacement.closeConnection();
                    assertFalse(replacement.commitText("late",1));assertFalse(replacement.finishComposingText());
                    assertFalse(replacement.performEditorAction(EditorInfo.IME_ACTION_DONE));assertTrue(sink.queue.isEmpty());
                    InputConnection current=display.onCreateInputConnection(new EditorInfo());
                    assertTrue(current.setComposingText("ok",1));assertTrue(current.performEditorAction(EditorInfo.IME_NULL));
                    sink.exact('o','o','k','k',ENTER,ENTER);return null;
                });hidden(display);

                InputConnection enter=open(button,display);
                ui(()->{sink.drain();assertTrue(enter.setComposingText("e",1));
                    assertTrue(enter.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_ENTER)));
                    assertFalse(enter.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP,KeyEvent.KEYCODE_ENTER)));
                    sink.exact('e','e',ENTER,ENTER);return null;
                });hidden(display);

                InputConnection plain=open(button,display);
                ui(()->{sink.drain();assertTrue(plain.setComposingText("a".repeat(64),1));
                    assertTrue(plain.performEditorAction(EditorInfo.IME_ACTION_DONE));assertEquals(130,sink.queue.size());assertTrue(sink.held.isEmpty());return null;
                });hidden(display);
                InputConnection shifted=open(button,display);
                ui(()->{sink.drain();assertTrue(shifted.setComposingText("A".repeat(64),1));int rejected=rejections.get();
                    assertFalse(shifted.performEditorAction(EditorInfo.IME_ACTION_DONE));assertEquals(rejected+1,rejections.get());
                    assertTrue(sink.queue.isEmpty());assertTrue(imeVisible(display));assertNull(failure.get());
                    assertTrue(shifted.setComposingText("short",1));assertTrue(shifted.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    sink.exact('s','s','h','h','o','o','r','r','t','t',ENTER,ENTER);return null;
                });hidden(display);

                InputConnection back=open(button,display);
                ui(()->{sink.drain();assertTrue(back.setComposingText("discard",1));
                    display.onKeyPreIme(KeyEvent.KEYCODE_BACK,new KeyEvent(KeyEvent.ACTION_UP,KeyEvent.KEYCODE_BACK));
                    assertFalse(back.commitText("late",1));assertFalse(back.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    assertTrue(sink.queue.isEmpty());return null;
                });hidden(display);

                boolean registeredController;
                String unavailableController;
                try(RegisteredInputFixture controls=RegisteredInputFixture.open(instrumentation)) {
                    registeredController=controls.device!=null;unavailableController=controls.unavailableReason;
                    if(registeredController) {
                        ui(()->{sink.drain();return null;});
                        sticks(display,controls.device.getId(),.8f,-.8f,.75f,-.5f);
                        ui(()->{assertTrue(sink.held.contains((int)'w'));assertTrue(sink.held.contains((int)'e'));
                            assertEquals(4,sink.mask);return null;});
                        waitFor(()->ui(()->sink.relativeCalls>0&&sink.dx>0&&sink.dy<0),
                                "Real Choreographer ticks must integrate constructed MotionEvents with registered joystick ranges");
                        sticks(display,controls.device.getId(),0,0,0,0);
                        ui(()->{assertTrue(sink.held.isEmpty());assertEquals(0,sink.mask);return null;});
                        sticks(display,controls.device.getId(),-.8f,0,.75f,0);
                        ui(()->{assertTrue(sink.held.contains((int)'q'));assertEquals(4,sink.mask);return null;});
                        int releases=ui(()->sink.releases);
                        controls.close();
                        waitFor(()->ui(()->sink.releases>releases&&sink.held.isEmpty()&&sink.mask==0),
                                "Actual registered controller removal must neutralize held movement and camera buttons");
                    }
                }

                ui(()->{sink.drain();assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BUTTON_A)));
                    assertTrue(sink.held.contains((int)' '));assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BUTTON_R2)));
                    assertEquals(4,sink.mask);int released=sink.releases;display.onInputDeviceRemoved(FIXED_KEY_EVENT_DEVICE);
                    assertTrue(sink.held.isEmpty());assertEquals(0,sink.mask);assertEquals(released+1,sink.releases);
                    assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BUTTON_Y)));
                    assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_UP,KeyEvent.KEYCODE_BUTTON_Y)));assertEquals(1,modeChanges.get());
                    assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_DPAD_UP)));
                    assertTrue(sink.held.contains(0xff52));display.pauseInput();assertTrue(sink.held.isEmpty());assertEquals(0,sink.mask);
                    int count=sink.queue.size();assertTrue(display.dispatchKeyEvent(key(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BUTTON_A)));
                    assertEquals(count,sink.queue.size());display.resumeInput();return null;
                });
                waitFor(()->frameUpdates.get()>=2,"Resume must reattach a real Surface writer before touch resumes");
                ui(()->{sink.drain();return null;});
                float[] middle=ui(()->new float[]{display.getWidth()/2f,display.getHeight()/2f});
                touch(display,MotionEvent.ACTION_DOWN,middle[0],middle[1]);
                ui(()->{assertEquals(1,sink.mask);assertEquals(1,sink.pointerX);assertEquals(0,sink.pointerY);return null;});
                touch(display,MotionEvent.ACTION_CANCEL,0,0);
                ui(()->{assertEquals(0,sink.mask);assertTrue(sink.held.isEmpty());return null;});

                InputConnection paused=open(button,display);
                ui(()->{sink.drain();assertTrue(paused.setComposingText("discard",1));display.pauseInput();display.hideKeyboard();
                    assertFalse(paused.finishComposingText());assertFalse(paused.performEditorAction(EditorInfo.IME_ACTION_DONE));
                    assertTrue(sink.queue.isEmpty());assertTrue(sink.held.isEmpty());assertEquals(0,sink.mask);return null;
                });hidden(display);
                assertNull(failure.get());assertEquals(1,sink.batchRefusals);
                JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-widget-ime-input-recording-component")
                    .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("api",Build.VERSION.SDK_INT)
                    .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("fingerprint",Build.FINGERPRINT).put("abi","x86_64")
                    .put("groupsPassed",8).put("recordingSinkCapacity",CAPACITY).put("batchCapacityRefusals",sink.batchRefusals)
                    .put("realWidgetSurfaceReady",true).put("touchKeyboardOpenedAndHidden",true).put("editorInfoVerified",true)
                    .put("composingDoneAtomic",true).put("softEnterAtomic",true).put("imeNullAtomic",true)
                    .put("wholeBatchRetryPreserved",true).put("replacedConnectionRefused",true).put("closedConnectionRefused",true)
                    .put("acceptedConnectionDuplicateRefused",true).put("plain64AndShiftedCapVerified",true)
                    .put("backAndPauseDiscardedDraft",true).put("controllerKeyEventsVerified",true).put("controllerRemovalReleased",true)
                    .put("controllerKeyEventsConstructed",true).put("controllerRemovalCallbackConstructed",true)
                    .put("controllerModeAndPauseReleased",true).put("touchPointerAndCancelVerified",true)
                    .put("recordingSinkOnly",true).put("androidWineExecuted",false).put("x11GuestExecuted",false)
                    .put("inputBridgeSocketExecuted",false).put("registeredControllerAvailable",registeredController)
                    .put("registeredControllerUnavailableReason",unavailableController)
                    .put("registeredControllerAxisRangeCount",registeredController?8:0)
                    .put("constructedMotionEventWithRealDevice",registeredController)
                    .put("registeredControllerEofRemovalVerified",registeredController)
                    .put("controllerStickMotionQualified",registeredController).put("controllerCameraMotionQualified",registeredController)
                    .put("kernelControllerEventDeliveryQualified",false).put("physicalControllerQualified",false)
                    .put("productionPresentationPanelSessionQualified",false).put("arm64Qualified",false)
                    .put("gameplayQualified",false).put("hardwareQualified",false);
                Files.write(context.getFilesDir().toPath().resolve("input-widget-qualification.json"),
                        receipt.toString(2).getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
            } finally {
                ui(()->{if(view.get()!=null){view.get().hideKeyboard();view.get().pauseInput();}
                    if(fixture.get()!=null&&fixture.get().getParent() instanceof ViewGroup)
                        ((ViewGroup)fixture.get().getParent()).removeView(fixture.get());return null;});
            }
        } finally {
            instrumentation.runOnMainSync(activity::finish);
            try(java.util.stream.Stream<Path> paths=Files.walk(root)){
                for(Path path:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator)Files.delete(path);
            }
        }
        assertFalse(Files.exists(root));
    }
}
