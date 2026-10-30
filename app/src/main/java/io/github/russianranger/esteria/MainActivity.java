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
import android.widget.ArrayAdapter;
import android.widget.Spinner;
import android.widget.FrameLayout;
import io.github.russianranger.esteria.runtime.GameSession;
import io.github.russianranger.esteria.presentation.GamePresentationPanel;
import io.github.russianranger.esteria.runtime.ClientLaunchSetup;
import java.util.ArrayList;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int BASE = 10, OVERLAY = 11, EXPORT = 12, BASE_FOLDER = 13, OVERLAY_FOLDER = 14;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<Button> actions = new ArrayList<>();
    private SessionService service;
    private TextView status;
    private Button cancel, useImportedUi, keepCurrentUi;
    private TextView uiReview;
    private String displayedUiDigest;
    private boolean bound;
    private Spinner clientLanguage;
    private FrameLayout rootView;
    private ScrollView launcher;
    private LinearLayout gameRoot;
    private GamePresentationPanel gamePanel;
    private GameSession.Handle boundGame;
    private TextView gameStatus;
    private Button startGame,exportSupport,forceStop,launcherForceStop;
    private boolean resumed;
    private static final String[] CLIENT_LOCALES={"enUS","enGB","ruRU","deDE","esES","esMX","frFR","koKR","zhCN","zhTW","enCN","enTW"};
    private final Runnable refresh = new Runnable() {
        public void run() {
            if (service != null) {
                status.setText(service.status());
                for (Button action : actions) action.setEnabled(!service.busy());
                startGame.setEnabled(!service.busy()&&completeProfile());
                exportSupport.setEnabled(!service.busy()||service.game()!=null);
                launcherForceStop.setVisibility(service.forceStopAvailable()?View.VISIBLE:View.GONE);
                launcherForceStop.setEnabled(service.forceStopAvailable());
                if(clientLanguage!=null)clientLanguage.setEnabled(!service.busy());
                cancel.setEnabled(service.busy());
                ClientLaunchSetup.UiReview review=service.uiReview();
                if(review==null) {
                    displayedUiDigest=null; uiReview.setVisibility(View.GONE);
                    useImportedUi.setVisibility(View.GONE); keepCurrentUi.setVisibility(View.GONE);
                } else {
                    // The click sends the digest of the report actually shown, never a newer service value.
                    if(!review.digest.equals(displayedUiDigest)) uiReview.setText(review.text);
                    displayedUiDigest=review.digest; uiReview.setVisibility(View.VISIBLE);
                    useImportedUi.setVisibility(View.VISIBLE); keepCurrentUi.setVisibility(View.VISIBLE);
                }
                syncGameView();
            }
            ui.postDelayed(this, 250);
        }
    };
    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            service = ((SessionService.LocalBinder) binder).service();
        }
        @Override public void onServiceDisconnected(ComponentName name) { detachGameView();service = null; }
    };
    @Override public void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);launcher=scroll;
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        int padding = dp(24); layout.setPadding(padding, padding, padding, padding); scroll.addView(layout);
        TextView title = text("ESTERIA", 34, Color.rgb(220, 186, 113)); layout.addView(title);
        TextView subtitle = text("Your local world", 18, Color.rgb(184, 199, 211)); layout.addView(subtitle);
        TextView explanation = text("Import your World of Warcraft 3.3.5a build 12340 client folder directly, or choose a ZIP. Custom content can be added later. Imported data stays in the app between updates.\n\nFolder imports avoid an extra archive copy. Keep the source folder unchanged until import finishes. ZIP imports need space for an archive copy and expanded files. Updates retain previous data versions; automatic cleanup is not available yet.\n\n"+(completeProfile()?"This build includes the local client/server session. Hardware rendering, world entry and gameplay validation are pending.":"This build has an incomplete runtime profile; gameplay is unavailable."), 15, Color.rgb(184, 199, 211));
        explanation.setPadding(0, dp(20), 0, dp(12)); layout.addView(explanation);
        button(layout, "Import client folder", () -> chooseFolder(BASE_FOLDER));
        button(layout, "Import client ZIP", () -> chooseArchive(BASE));
        button(layout, "Add custom content folder", () -> chooseFolder(OVERLAY_FOLDER));
        button(layout, "Add custom content ZIP", () -> chooseArchive(OVERLAY));
        button(layout, "Prepare client runtime", () -> operation(new Intent(this, SessionService.class).setAction(SessionService.PREPARE_RUNTIME)));
        TextView runtimeNote = text("Initial runtime setup may download files. Progress shows the copied size; interrupted setup can resume. Previous versions and imported game data are retained.", 13, Color.rgb(145, 163, 177));
        layout.addView(runtimeNote);
        if (BuildConfig.SERVER_RUNTIME_PACKAGED) {
            button(layout, "Prepare server dependencies · bundled", () -> operation(new Intent(this, SessionService.class).setAction(SessionService.PREPARE_SERVER_RUNTIME)));
            layout.addView(text("Prepare the bundled server files before preparing the local world. Imported game data, database files and saved characters are stored separately from application updates.", 13, Color.rgb(145, 163, 177)));
        }
        if(BuildConfig.SERVER_DATA_TOOLS_PACKAGED&&BuildConfig.SERVER_PROGRAMS_PACKAGED&&BuildConfig.SERVER_CONTENT_PACKAGED&&BuildConfig.SHADER_TOOLS_PACKAGED) {
            layout.addView(text("Imported client language",14,Color.rgb(184,199,211)));
            clientLanguage=new Spinner(this);
            ArrayAdapter<String> languages=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,CLIENT_LOCALES);
            languages.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);clientLanguage.setAdapter(languages);
            String selected=getPreferences(MODE_PRIVATE).getString("clientLanguage","enUS");
            for(int i=0;i<CLIENT_LOCALES.length;i++)if(CLIENT_LOCALES[i].equals(selected))clientLanguage.setSelection(i);
            layout.addView(clientLanguage);
            button(layout,"Prepare local world",()->{
                String locale=(String)clientLanguage.getSelectedItem();
                getPreferences(MODE_PRIVATE).edit().putString("clientLanguage",locale).apply();
                operation(new Intent(this,SessionService.class).setAction(SessionService.PREPARE_WORLD).putExtra(SessionService.WORLD_LOCALE,locale));
            });
            layout.addView(text("This prepares world data, graphics data and the local database. Use the language of the imported client. Initial preparation can take a long time; completed stages are reused. Fresh database setup reserves 4 GiB in addition to world data.",13,Color.rgb(145,163,177)));
        }
        uiReview=text("",14,Color.rgb(220,186,113)); uiReview.setTextIsSelectable(true);
        uiReview.setPadding(0,dp(16),0,dp(8)); uiReview.setVisibility(View.GONE); layout.addView(uiReview);
        useImportedUi=button(layout,"Use imported UI version",()->reviewDecision(SessionService.ACCEPT_UI));
        keepCurrentUi=button(layout,"Keep current UI",()->reviewDecision(SessionService.KEEP_UI));
        useImportedUi.setVisibility(View.GONE); keepCurrentUi.setVisibility(View.GONE);
        startGame=button(layout, "Start local game", () -> {
            Intent intent=new Intent(this,SessionService.class).setAction(SessionService.START);
            if(clientLanguage!=null)intent.putExtra(SessionService.WORLD_LOCALE,(String)clientLanguage.getSelectedItem());
            operation(intent);
        });startGame.setEnabled(completeProfile());
        exportSupport=button(layout, "Export support bundle", this::chooseExport);
        cancel = new Button(this); cancel.setText(R.string.stop_session); cancel.setEnabled(false);
        cancel.setOnClickListener(v -> startService(new Intent(this, SessionService.class).setAction(SessionService.CANCEL))); layout.addView(cancel);
        launcherForceStop=button(layout,"Force stop client · unsaved state may be lost",()->
            startService(new Intent(this,SessionService.class).setAction(SessionService.FORCE_STOP)));
        launcherForceStop.setVisibility(View.GONE);
        status = text("Connecting to local storage…", 16, Color.WHITE); status.setTextIsSelectable(true);
        status.setPadding(0, dp(20), 0, dp(12)); layout.addView(status);
        TextView controls = text("D-pad: navigate · A: choose · B: minimize\nLB / RB: previous / next control", 13, Color.rgb(145, 163, 177)); layout.addView(controls);
        rootView=new FrameLayout(this);rootView.addView(scroll,new FrameLayout.LayoutParams(-1,-1));setContentView(rootView);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
    }
    private Button button(LinearLayout layout, String label, Runnable action) {
        Button button = new Button(this); button.setText(label); button.setOnClickListener(v -> action.run());
        button.setFocusable(true); actions.add(button); layout.addView(button); return button;
    }
    private TextView text(String text, int size, int color) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color); return view;
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private static boolean completeProfile(){return BuildConfig.PROOT_PACKAGED&&BuildConfig.CLIENT_RUNTIME_PACKAGED&&BuildConfig.GUEST_BRIDGES_PACKAGED&&
        BuildConfig.TURNIP_PACKAGED&&BuildConfig.SERVER_RUNTIME_PACKAGED&&BuildConfig.SERVER_PROGRAMS_PACKAGED&&BuildConfig.SERVER_CONTENT_PACKAGED&&
        BuildConfig.SERVER_DATA_TOOLS_PACKAGED&&BuildConfig.SHADER_TOOLS_PACKAGED;}
    /** Activities own views only. Rebinding never starts/stops a native process. */
    private void syncGameView() {
        GameSession.Handle owner=service==null?null:service.game();
        if(owner==null){detachGameView();return;}
        if(boundGame!=owner) {
            if(owner.state()!=GameSession.State.CLIENT_STARTED||owner.presentation()==null||!owner.presentation().isReady()||service.presentationEvents()==null)return;
            detachGameView();
            gameRoot=new LinearLayout(this);gameRoot.setOrientation(LinearLayout.VERTICAL);gameRoot.setBackgroundColor(Color.BLACK);
            gamePanel=new GamePresentationPanel(this,service.presentationEvents(),()->startService(new Intent(this,SessionService.class).setAction(SessionService.CANCEL)));
            try{gamePanel.bind(owner.presentation());}catch(java.io.IOException error){gamePanel=null;gameRoot=null;return;}
            gameRoot.addView(gamePanel,new LinearLayout.LayoutParams(-1,0,1));
            gameStatus=text("",13,Color.WHITE);gameStatus.setPadding(dp(12),dp(4),dp(12),dp(4));gameRoot.addView(gameStatus);
            LinearLayout tools=new LinearLayout(this);
            Button support=new Button(this);support.setText("Support bundle");support.setOnClickListener(v->chooseExport());tools.addView(support,new LinearLayout.LayoutParams(0,-2,1));
            forceStop=new Button(this);forceStop.setText("Force stop");forceStop.setVisibility(View.GONE);
            forceStop.setOnClickListener(v->startService(new Intent(this,SessionService.class).setAction(SessionService.FORCE_STOP)));
            tools.addView(forceStop,new LinearLayout.LayoutParams(0,-2,1));gameRoot.addView(tools);
            rootView.addView(gameRoot,new FrameLayout.LayoutParams(-1,-1));launcher.setVisibility(View.GONE);boundGame=owner;
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            if(resumed)gamePanel.resume();
        }
        if(gameStatus!=null)gameStatus.setText(service.status());
        if(forceStop!=null){forceStop.setVisibility(owner.needsForceStop()?View.VISIBLE:View.GONE);forceStop.setEnabled(owner.needsForceStop());}
        if(owner.state()!=GameSession.State.CLIENT_STARTED&&gamePanel!=null)gamePanel.pause();
    }
    private void detachGameView() {
        if(gamePanel!=null){gamePanel.pause();gamePanel.unbind();}
        if(gameRoot!=null)rootView.removeView(gameRoot);
        gamePanel=null;gameRoot=null;gameStatus=null;forceStop=null;boundGame=null;
        if(launcher!=null)launcher.setVisibility(View.VISIBLE);
        getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }
    private void chooseArchive(int request) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, request);
    }
    private void chooseFolder(int request) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
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
        if (request == BASE || request == OVERLAY || request == BASE_FOLDER || request == OVERLAY_FOLDER) {
            try {
                int readGrant = data.getFlags() & Intent.FLAG_GRANT_READ_URI_PERMISSION;
                if (readGrant != 0) getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
            }
            catch (SecurityException ignored) { /* The current grant still permits this import. */ }
            operation(new Intent(this, SessionService.class).setAction(SessionService.IMPORT).setData(uri)
                    .putExtra("overlay", request == OVERLAY || request == OVERLAY_FOLDER)
                    .putExtra("folder", request == BASE_FOLDER || request == OVERLAY_FOLDER));
        } else if (request == EXPORT) operation(new Intent(this, SessionService.class).setAction(SessionService.EXPORT).setData(uri));
    }
    private void reviewDecision(String action) {
        String digest=displayedUiDigest;
        if(digest!=null)operation(new Intent(this,SessionService.class).setAction(action)
                .putExtra(SessionService.UI_REVIEW_DIGEST,digest));
    }
    private void operation(Intent intent) { startForegroundService(intent); }
    @Override protected void onStart() {
        super.onStart(); bound = bindService(new Intent(this, SessionService.class), connection, BIND_AUTO_CREATE); ui.post(refresh);
    }
    @Override protected void onStop() {
        ui.removeCallbacks(refresh);detachGameView();if (bound) { unbindService(connection); bound = false; } service = null; super.onStop();
    }
    @Override protected void onResume(){super.onResume();resumed=true;if(gamePanel!=null)gamePanel.resume();}
    @Override protected void onPause(){resumed=false;if(gamePanel!=null)gamePanel.pause();super.onPause();}
    @Override public boolean onKeyDown(int code, KeyEvent event) {
        if(gamePanel!=null&&code!=KeyEvent.KEYCODE_BUTTON_B)return super.onKeyDown(code,event);
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
