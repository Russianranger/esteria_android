package io.github.russianranger.esteria;

import android.Manifest;
import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int BASE = 10, OVERLAY = 11, EXPORT = 12;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<Button> actions = new ArrayList<>();
    private SessionService service;
    private TextView status;
    private Button cancel;
    private boolean bound;
    private final Runnable refresh = new Runnable() {
        public void run() {
            if (service != null) {
                status.setText(service.status());
                for (Button action : actions) action.setEnabled(!service.busy());
                cancel.setEnabled(service.busy());
            }
            ui.postDelayed(this, 250);
        }
    };
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            service = ((SessionService.LocalBinder) binder).service();
        }
        @Override public void onServiceDisconnected(ComponentName name) { service = null; }
    };
    @Override public void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(24); layout.setPadding(padding, padding, padding, padding); scroll.addView(layout);
        TextView title = text("ESTERIA", 34, Color.rgb(220, 186, 113)); layout.addView(title);
        TextView subtitle = text("Your local world", 18, Color.rgb(184, 199, 211)); layout.addView(subtitle);
        TextView explanation = text("Import a World of Warcraft 3.3.5a build 12340 client ZIP. Custom content can be added later. Your imported data stays in the app between updates.\n\nZIP imports need space for an archive copy and the expanded files. Updates also keep previous data versions; automatic cleanup is not available yet.\n\nGameplay is unavailable in this development build.", 15, Color.rgb(184, 199, 211));
        explanation.setPadding(0, dp(20), 0, dp(12)); layout.addView(explanation);
        button(layout, "Import client ZIP", () -> chooseArchive(BASE));
        button(layout, "Add custom content ZIP", () -> chooseArchive(OVERLAY));
        button(layout, "Start local game", () -> operation(new Intent(this, SessionService.class).setAction(SessionService.START)));
        button(layout, "Export support bundle", this::chooseExport);
        cancel = new Button(this); cancel.setText(R.string.stop_session); cancel.setEnabled(false);
        cancel.setOnClickListener(v -> startService(new Intent(this, SessionService.class).setAction(SessionService.CANCEL))); layout.addView(cancel);
        status = text("Connecting to local storage…", 16, Color.WHITE); status.setTextIsSelectable(true);
        status.setPadding(0, dp(20), 0, dp(12)); layout.addView(status);
        TextView controls = text("D-pad: navigate · A: choose · B: minimize\nLB / RB: previous / next control", 13, Color.rgb(145, 163, 177)); layout.addView(controls);
        setContentView(scroll);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
    }
    private void button(LinearLayout layout, String label, Runnable action) {
        Button button = new Button(this); button.setText(label); button.setOnClickListener(v -> action.run());
        button.setFocusable(true); actions.add(button); layout.addView(button);
    }
    private TextView text(String text, int size, int color) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color); return view;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void chooseArchive(int request) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, request);
    }
    private void chooseExport() {
        startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/zip")
                .addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, "Esteria-support-" + System.currentTimeMillis() + ".zip"), EXPORT);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (request == BASE || request == OVERLAY) {
            try {
                int readGrant = data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION;
                if (readGrant != 0) getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            }
            catch (SecurityException ignored) { /* The current grant still permits this import. */ }
            operation(new Intent(this, SessionService.class).setAction(SessionService.IMPORT).setData(uri).putExtra("overlay", request == OVERLAY));
        } else if (request == EXPORT) operation(new Intent(this, SessionService.class).setAction(SessionService.EXPORT).setData(uri));
    }
    private void operation(Intent intent) { startForegroundService(intent); }
    @Override protected void onStart() {
        super.onStart(); bound = bindService(new Intent(this, SessionService.class), connection, BIND_AUTO_CREATE); ui.post(refresh);
    }
    @Override protected void onStop() {
        ui.removeCallbacks(refresh); if (bound) { unbindService(connection); bound = false; } service = null; super.onStop();
    }
    @Override public boolean onKeyDown(int code, KeyEvent event) {
        if (code == KeyEvent.KEYCODE_BUTTON_B) { if (event.getRepeatCount() == 0) moveTaskToBack(true); return true; }
        if (code == KeyEvent.KEYCODE_BUTTON_A) {
            View focus = getCurrentFocus(); if (event.getRepeatCount() == 0 && focus != null) focus.performClick(); return true;
        }
        if (code == KeyEvent.KEYCODE_BUTTON_L1 || code == KeyEvent.KEYCODE_BUTTON_R1) {
            View focus = getCurrentFocus(); View next = focus == null ? actions.get(0) : focus.focusSearch(code == KeyEvent.KEYCODE_BUTTON_L1 ? View.FOCUS_UP : View.FOCUS_DOWN);
            if (next != null) next.requestFocus(); return true;
        }
        return super.onKeyDown(code, event);
    }
}
