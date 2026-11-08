package io.github.russianranger.esteria;

import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.widget.FrameLayout;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.presentation.SettingsGear;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public final class RealmInterfaceTest {
    @Test public void launcherPagesAndMovableGear() {
        Instrumentation test=InstrumentationRegistry.getInstrumentation();
        Context context=test.getTargetContext();
        MainActivity screen=(MainActivity)test.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        test.waitForIdleSync();
        try {
            test.runOnMainSync(()->{
                FrameLayout content=screen.findViewById(android.R.id.content);
                RealmLauncher launcher=(RealmLauncher)((FrameLayout)content.getChildAt(0)).getChildAt(0);
                assertTrue(launcher.play.isShown());
                assertFalse(launcher.setup.isShown());
                launcher.select(1);
                assertTrue(screen.findViewById(R.id.preparation_speed).isShown());
                launcher.select(2);
                assertTrue(launcher.tools.isShown());
                AtomicInteger opens=new AtomicInteger();
                FrameLayout frame=new FrameLayout(screen);
                content.addView(frame,new FrameLayout.LayoutParams(600,320));
                SettingsGear gear=new SettingsGear(screen,frame,opens::incrementAndGet);
                try{
                    measure(frame,600,320);
                    gear.resetPosition();
                    float before=gear.getX();
                    touch(gear,MotionEvent.ACTION_DOWN,10,10);
                    touch(gear,MotionEvent.ACTION_MOVE,-140,85);
                    touch(gear,MotionEvent.ACTION_UP,-140,85);
                    assertEquals(0,opens.get());
                    assertTrue(gear.getX()<before);
                    FrameLayout second=new FrameLayout(screen);
                    SettingsGear restored=new SettingsGear(screen,second,opens::incrementAndGet);
                    measure(second,600,320);
                    assertEquals(gear.getX(),restored.getX(),1f);
                    assertEquals(gear.getY(),restored.getY(),1f);
                    touch(restored,MotionEvent.ACTION_DOWN,12,12);
                    touch(restored,MotionEvent.ACTION_UP,12,12);
                    assertEquals(1,opens.get());
                    measure(second,320,600);
                    assertTrue(restored.getX()>=0 && restored.getX()+restored.getWidth()<=320);
                }finally{gear.resetPosition();content.removeView(frame);}
            });
        }finally{test.runOnMainSync(screen::finish);}
    }
    private static void measure(View v,int w,int h){
        v.measure(View.MeasureSpec.makeMeasureSpec(w,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(h,View.MeasureSpec.EXACTLY));
        v.layout(0,0,w,h);
    }
    private static void touch(View v,int action,float x,float y){
        long now=SystemClock.uptimeMillis();
        MotionEvent e=MotionEvent.obtain(now,now,action,x,y,0);
        try{v.dispatchTouchEvent(e);}finally{e.recycle();}
    }
}
