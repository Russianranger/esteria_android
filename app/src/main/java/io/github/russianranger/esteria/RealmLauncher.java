package io.github.russianranger.esteria;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** Small-screen realm selection and maintenance pages. The landscape stays fixed while a page scrolls. */
final class RealmLauncher extends FrameLayout {
    static final int GOLD = 0xffe1bc76, INK = 0xff211c15, PAPER = 0xfff5edda;
    final LinearLayout play, setup, tools, footer;
    private final LinearLayout[] pages = new LinearLayout[3];
    private final Button[] tabs = new Button[3];
    private final ScrollView scroll;
    private final Activity activity;
    private final Typeface display;
    private int selected;

    RealmLauncher(Activity activity, int initialPage) {
        super(activity);
        this.activity = activity;
        display = getResources().getFont(R.font.cinzel);
        ImageView art = new ImageView(activity);
        art.setImageResource(R.drawable.mulgore);
        art.setScaleType(ImageView.ScaleType.CENTER_CROP);
        art.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        addView(art, new LayoutParams(-1, -1));
        scroll = new ScrollView(activity);
        scroll.setFillViewport(true);
        scroll.setBackground(new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                new int[]{0xfa15201e, 0xf71c2421, 0xed22271f}));
        addView(scroll, new LayoutParams(-1, -1, Gravity.START));
        LinearLayout column = column();
        column.setPadding(dp(22), dp(18), dp(22), dp(12));
        scroll.addView(column);
        TextView title = label("Esteria", 40, GOLD);
        title.setIncludeFontPadding(false);
        title.setTypeface(display, Typeface.BOLD);
        column.addView(title);
        column.addView(label("Local realm   ·   Stock 3.3.5a", 14, PAPER));
        LinearLayout navigation = new LinearLayout(activity);
        LinearLayout.LayoutParams navSize = new LinearLayout.LayoutParams(-1,-2);
        navSize.setMargins(0,dp(14),0,dp(8));
        column.addView(navigation,navSize);
        String[] names = {"Play","Setup","Tools"};
        for (int i=0;i<names.length;i++) {
            final int page=i;
            Button tab = new Button(activity);
            tab.setText(names[i]); tab.setAllCaps(false);
            tab.setTypeface(display, Typeface.BOLD);
            tab.setPadding(0,0,0,0); tab.setMinWidth(0); tab.setMinimumWidth(0);
            tab.setOnClickListener(v -> select(page));
            tabs[i]=tab;
            navigation.addView(tab,new LinearLayout.LayoutParams(0,dp(48),1));
        }
        for (int i=0;i<pages.length;i++) {pages[i]=column(); column.addView(pages[i]);}
        play=pages[0]; setup=pages[1]; tools=pages[2];
        footer=column(); column.addView(footer);
        select(initialPage);
    }
    int selectedPage() {return selected;}
    void select(int page) {
        selected = Math.max(0,Math.min(pages.length-1,page));
        for (int i=0;i<pages.length;i++) {
            boolean active = i==selected;
            pages[i].setVisibility(active ? View.VISIBLE : View.GONE);
            tabs[i].setSelected(active);
            tabs[i].setTextColor(active ? INK : PAPER);
            tabs[i].setBackground(background(active));
        }
        scroll.scrollTo(0,0);
    }
    @Override protected void onMeasure(int w,int h) {
        // The art gets a full horizon on a handheld, while portrait retains usable controls.
        scroll.getLayoutParams().width=Math.min(MeasureSpec.getSize(w),dp(360));
        super.onMeasure(w,h);
    }
    void style(Button button,boolean primary) {
        button.setAllCaps(false);
        button.setTextSize(primary?19:15);
        if(primary)button.setTypeface(display,Typeface.BOLD);
        button.setGravity(Gravity.CENTER);
        button.setTextColor(new ColorStateList(new int[][]{new int[]{-android.R.attr.state_enabled},new int[]{}},
                new int[]{0xffaaa79c,primary?INK:PAPER}));
        button.setBackground(background(primary));
        button.setPadding(dp(10),dp(6),dp(10),dp(6));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);
        lp.setMargins(0,dp(3),0,dp(3));
        button.setLayoutParams(lp); button.setMinHeight(dp(primary?54:48));
    }
    private StateListDrawable background(boolean primary) {
        StateListDrawable states = new StateListDrawable();
        states.addState(new int[]{-android.R.attr.state_enabled},plate(0xff343935,0xff54584d));
        states.addState(new int[]{android.R.attr.state_pressed},plate(0xff997947,0xffffde94));
        states.addState(new int[]{android.R.attr.state_focused},plate(primary?0xffe6c995:0xff485449,0xffffe8a0));
        states.addState(new int[]{},plate(primary?0xffd7b677:0xff293630,primary?0xfff4d996:0xff736649));
        return states;
    }
    private GradientDrawable plate(int color,int rim) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color); shape.setStroke(dp(1),rim); shape.setCornerRadius(dp(4));
        return shape;
    }
    private LinearLayout column(){LinearLayout c=new LinearLayout(activity);c.setOrientation(LinearLayout.VERTICAL);return c;}
    private TextView label(String value,int size,int color){
        TextView label=new TextView(activity);label.setText(value);label.setTextSize(size);label.setTextColor(color);return label;
    }
    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
}
