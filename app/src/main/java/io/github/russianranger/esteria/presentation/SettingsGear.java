package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.drawable.GradientDrawable;
import android.view.MotionEvent;
import android.view.ViewConfiguration;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import io.github.russianranger.esteria.R;

/** A touch target above the SurfaceView. Persist a fraction of the available travel, so rotation is safe. */
public final class SettingsGear extends ImageButton {
    private final SharedPreferences prefs;
    private final FrameLayout bounds;
    private final int slop;
    private float startX,startY,originX,originY;
    private boolean dragged;
    private int pointer=-1;

    public SettingsGear(Context context,FrameLayout bounds,Runnable open) {
        super(context);
        this.bounds=bounds;
        prefs=context.getSharedPreferences("game-display",Context.MODE_PRIVATE);
        slop=ViewConfiguration.get(context).getScaledTouchSlop();
        setImageResource(R.drawable.ic_game_settings);
        setContentDescription("Advanced game settings. Drag to move.");
        GradientDrawable bezel=new GradientDrawable();
        bezel.setShape(GradientDrawable.OVAL);bezel.setColor(0xe5232c28);bezel.setStroke(dp(2),0xffd4b373);
        setBackground(bezel);setPadding(dp(11),dp(11),dp(11),dp(11));
        setOnClickListener(v -> open.run());
        bounds.addView(this,new FrameLayout.LayoutParams(dp(48),dp(48)));
        bounds.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or,ob)->restore());
    }
    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private int travelX(){return Math.max(0,bounds.getWidth()-getWidth());}
    private int travelY(){return Math.max(0,bounds.getHeight()-getHeight());}
    private static float clamp(float x,float max){return Math.max(0,Math.min(x,max));}
    private void restore(){
        setX(clamp(prefs.getFloat("gearX",0.97f)*travelX(),travelX()));
        setY(clamp(prefs.getFloat("gearY",0.08f)*travelY(),travelY()));
    }
    public void resetPosition(){prefs.edit().remove("gearX").remove("gearY").apply();restore();}
    @Override public boolean onTouchEvent(MotionEvent e) {
        int action=e.getActionMasked();
        if(action==MotionEvent.ACTION_DOWN){
            pointer=e.getPointerId(0);startX=e.getRawX();startY=e.getRawY();originX=getX();originY=getY();
            dragged=false;setPressed(true);return true;
        }
        if(action==MotionEvent.ACTION_CANCEL || action==MotionEvent.ACTION_POINTER_DOWN){
            pointer=-1;setPressed(false);restore();return true;
        }
        if(pointer<0 || e.getPointerId(0)!=pointer)return true;
        float dx=e.getRawX()-startX,dy=e.getRawY()-startY;
        if(action==MotionEvent.ACTION_MOVE || action==MotionEvent.ACTION_UP){
            dragged|=dx*dx+dy*dy>slop*slop;
            if(dragged){setX(clamp(originX+dx,travelX()));setY(clamp(originY+dy,travelY()));}
        }
        if(action==MotionEvent.ACTION_UP){
            pointer=-1;setPressed(false);
            if(dragged)prefs.edit().putFloat("gearX",getX()/Math.max(1,travelX())).putFloat("gearY",getY()/Math.max(1,travelY())).apply();
            else performClick();
        }
        return true;
    }
    @Override public boolean performClick(){return super.performClick();}
}
