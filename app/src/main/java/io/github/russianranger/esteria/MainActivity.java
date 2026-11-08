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
import android.widget.AdapterView;
import android.widget.FrameLayout;
import io.github.russianranger.esteria.core.runtime.install.PreparationSpeed;
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
    private Spinner preparationSpeed;
    private TextView storageSummary;
    private Button scanStorage, trimStorage;
    private FrameLayout rootView;
    private RealmLauncher launcher;
    private FrameLayout gameRoot;
    private io.github.russianranger.esteria.presentation.SettingsGear gear;
    private android.app.AlertDialog gameSettings;
    private GamePresentationPanel gamePanel;
    private GameSession.Handle boundGame;

    private Button startGame,exportSupport,launcherForceStop;
    private boolean resumed;
    private static final String[] CLIENT_LOCALES={"enUS","enGB","ruRU","deDE","esES","esMX","frFR","koKR","zhCN","zhTW","enCN","enTW"};
    private final Runnable refresh = new Runnable() {
        public void run() {
            if (service != null) {
                String latestStatus = service.status();
                if (!android.text.TextUtils.equals(status.getText(), latestStatus)) status.setText(latestStatus);
                for (Button action : actions) action.setEnabled(!service.busy());
                startGame.setEnabled(!service.busy()&&completeProfile());
                exportSupport.setEnabled(service.supportExportAvailable());
                launcherForceStop.setVisibility(service.forceStopAvailable()?View.VISIBLE:View.GONE);
                launcherForceStop.setEnabled(service.forceStopAvailable());
                if(clientLanguage!=null)clientLanguage.setEnabled(!service.busy());
                preparationSpeed.setEnabled(!service.busy());
                scanStorage.setEnabled(service.storageMaintenanceAvailable());
                trimStorage.setEnabled(service.storageTrimAvailable());
                if(!android.text.TextUtils.equals(storageSummary.getText(),service.storageStatus()))storageSummary.setText(service.storageStatus());
                cancel.setEnabled(service.busy());
                cancel.setVisibility(service.busy()?View.VISIBLE:View.GONE);
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
        launcher = new RealmLauncher(this,savedState==null?0:savedState.getInt("realmPage",0));
        LinearLayout layout = launcher.setup;
        layout.addView(text("Import your build 12340 client folder or ZIP, then prepare the local world.",15,RealmLauncher.PAPER));
        button(layout, "Import client folder", () -> chooseFolder(BASE_FOLDER));
        button(layout, "Import client ZIP", () -> chooseArchive(BASE));
        layout.addView(text("World preparation speed",14,Color.rgb(184,199,211)));
        preparationSpeed=new Spinner(this);preparationSpeed.setId(R.id.preparation_speed);
        PreparationSpeed[] speeds=PreparationSpeed.values();
        String[] speedLabels=new String[speeds.length];for(int i=0;i<speeds.length;i++)speedLabels[i]=speeds[i].label;
        ArrayAdapter<String> speedAdapter=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,speedLabels);
        speedAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);preparationSpeed.setAdapter(speedAdapter);
        PreparationSpeed savedSpeed=PreparationSpeed.DEFAULT;
        try{savedSpeed=PreparationSpeed.fromId(getSharedPreferences("preparation",MODE_PRIVATE).getString("speed",PreparationSpeed.DEFAULT.id));}
        catch(IllegalArgumentException invalid){getSharedPreferences("preparation",MODE_PRIVATE).edit().remove("speed").apply();}
        preparationSpeed.setSelection(savedSpeed.ordinal());
        preparationSpeed.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onItemSelected(AdapterView<?> parent,View view,int position,long id){
                getSharedPreferences("preparation",MODE_PRIVATE).edit().putString("speed",speeds[position].id).apply();
            }
            public void onNothingSelected(AdapterView<?> parent){ }
        });
        layout.addView(preparationSpeed);
        layout.addView(text("Controls preparation speed. Completed work is reused.",13,Color.rgb(145,163,177)));
        if(BuildConfig.SERVER_DATA_TOOLS_PACKAGED&&BuildConfig.SERVER_PROGRAMS_PACKAGED&&BuildConfig.SERVER_CONTENT_PACKAGED&&BuildConfig.SHADER_TOOLS_PACKAGED) {
            layout.addView(text("Imported client language",14,Color.rgb(184,199,211)));
            clientLanguage=new Spinner(this);
            ArrayAdapter<String> languages=new ArrayAdapter<>(this,android.R.layout.simple_spinner_item,CLIENT_LOCALES);
            languages.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);clientLanguage.setAdapter(languages);
            String selected=getPreferences(MODE_PRIVATE).getString("clientLanguage","enUS");
            for(int i=0;i<CLIENT_LOCALES.length;i++)if(CLIENT_LOCALES[i].equals(selected))clientLanguage.setSelection(i);
            layout.addView(clientLanguage);
            button(layout,"Prepare / fully verify local runtime and world",()->{
                String locale=(String)clientLanguage.getSelectedItem();
                getPreferences(MODE_PRIVATE).edit().putString("clientLanguage",locale).apply();
                operation(new Intent(this,SessionService.class).setAction(SessionService.PREPARE_WORLD).putExtra(SessionService.WORLD_LOCALE,locale));
            });

            button(launcher.tools,"Repair local component",()->{
                io.github.russianranger.esteria.runtime.LocalWorldSetup.Component[] components=io.github.russianranger.esteria.runtime.LocalWorldSetup.Component.values();
                String[] labels=new String[components.length];for(int i=0;i<components.length;i++)labels[i]=components[i].label;
                new android.app.AlertDialog.Builder(this).setTitle("Choose the component reported as not ready")
                    .setItems(labels,(dialog,index)->{
                        String locale=(String)clientLanguage.getSelectedItem();
                        operation(new Intent(this,SessionService.class).setAction(SessionService.PREPARE_WORLD)
                            .putExtra(SessionService.WORLD_LOCALE,locale).putExtra(SessionService.REPAIR_COMPONENT,components[index].name()));
                    }).setNegativeButton("Cancel",null).show();
            });

        }
        layout=launcher.play;
        uiReview=text("",14,Color.rgb(220,186,113)); uiReview.setTextIsSelectable(true);
        uiReview.setPadding(0,dp(16),0,dp(8)); uiReview.setVisibility(View.GONE); layout.addView(uiReview);
        useImportedUi=button(layout,"Use imported UI version",()->reviewDecision(SessionService.ACCEPT_UI));
        keepCurrentUi=button(layout,"Keep current UI",()->reviewDecision(SessionService.KEEP_UI));
        useImportedUi.setVisibility(View.GONE); keepCurrentUi.setVisibility(View.GONE);
        startGame=button(layout, "Start local game", () -> {
            Intent intent=new Intent(this,SessionService.class).setAction(SessionService.START);
            if(clientLanguage!=null)intent.putExtra(SessionService.WORLD_LOCALE,(String)clientLanguage.getSelectedItem());
            operation(intent);
        });startGame.setEnabled(completeProfile());launcher.style(startGame,true);
        if(!completeProfile())layout.addView(text("This installation has an incomplete runtime profile.",14,RealmLauncher.GOLD));
        button(layout,"Game settings",this::showDisplaySettings);
        layout=launcher.tools;
        exportSupport=button(layout,"Export support bundle",this::chooseExport);
        scanStorage=button(layout,"Check reclaimable storage",()->operation(new Intent(this,SessionService.class).setAction(SessionService.SCAN_STORAGE)));
        trimStorage=button(layout,"Trim obsolete files",()->operation(new Intent(this,SessionService.class).setAction(SessionService.TRIM_STORAGE)));
        trimStorage.setEnabled(false);
        storageSummary=text("Check how much space can be reclaimed from obsolete runtime files.",13,Color.rgb(145,163,177));layout.addView(storageSummary);
        layout=launcher.footer;
        cancel = new Button(this); cancel.setText(R.string.stop_session); cancel.setEnabled(false); cancel.setVisibility(View.GONE);
        cancel.setOnClickListener(v -> startService(new Intent(this, SessionService.class).setAction(SessionService.CANCEL))); layout.addView(cancel);launcher.style(cancel,false);
        launcherForceStop=button(layout,"Force stop client · unsaved state may be lost",()->
            startService(new Intent(this,SessionService.class).setAction(SessionService.FORCE_STOP)));
        launcherForceStop.setVisibility(View.GONE);
        status = text("Connecting to local storage…", 16, Color.WHITE); status.setTextIsSelectable(true);
        status.setPadding(0, dp(20), 0, dp(12)); layout.addView(status);
        rootView=new FrameLayout(this);rootView.addView(launcher,new FrameLayout.LayoutParams(-1,-1));setContentView(rootView);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 20);
    }
    private Button button(LinearLayout layout, String label, Runnable action) {
        Button button = new Button(this); button.setText(label); button.setOnClickListener(v -> action.run());
        button.setFocusable(true); actions.add(button); layout.addView(button); launcher.style(button,false); return button;
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
            gameRoot=new FrameLayout(this);gameRoot.setBackgroundColor(Color.BLACK);
            gamePanel=new GamePresentationPanel(this,service.presentationEvents(),()->startService(new Intent(this,SessionService.class).setAction(SessionService.CANCEL)));
            try{gamePanel.bind(owner.presentation());}catch(java.io.IOException error){gamePanel=null;gameRoot=null;return;}
            gameRoot.addView(gamePanel,new FrameLayout.LayoutParams(-1,-1));
            gear=new io.github.russianranger.esteria.presentation.SettingsGear(this,gameRoot,this::showGameSettings);
            rootView.addView(gameRoot,new FrameLayout.LayoutParams(-1,-1));launcher.setVisibility(View.GONE);boundGame=owner;
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            immersive(true);
            if(resumed)gamePanel.resume();
        }
        if(owner.state()!=GameSession.State.CLIENT_STARTED&&gamePanel!=null)gamePanel.pause();
    }
    private void detachGameView() {
        if(gameRoot==null)return;
        if(gameSettings!=null)gameSettings.dismiss();
        if(gamePanel!=null){gamePanel.pause();gamePanel.unbind();}
        if(gameRoot!=null)rootView.removeView(gameRoot);
        gamePanel=null;gameRoot=null;gear=null;boundGame=null;immersive(false);
        if(launcher!=null)launcher.setVisibility(View.VISIBLE);
        getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }
    @SuppressWarnings("deprecation")
    private void immersive(boolean active){
        if(Build.VERSION.SDK_INT>=30){
            android.view.WindowInsetsController bars=getWindow().getInsetsController();
            if(bars!=null){
                bars.setSystemBarsBehavior(android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                if(active)bars.hide(android.view.WindowInsets.Type.systemBars());else bars.show(android.view.WindowInsets.Type.systemBars());
            }
        }else getWindow().getDecorView().setSystemUiVisibility(active?
                View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY:View.SYSTEM_UI_FLAG_VISIBLE);
    }
    @Override public void onWindowFocusChanged(boolean focus){
        super.onWindowFocusChanged(focus);
        if(focus && gamePanel!=null)immersive(true);
    }
    @Override protected void onSaveInstanceState(Bundle out){
        super.onSaveInstanceState(out);out.putInt("realmPage",launcher.selectedPage());
    }
    @Override public void onBackPressed(){
        if(gamePanel!=null){showGameSettings();return;}
        if(launcher.selectedPage()!=0){launcher.select(0);return;}
        super.onBackPressed();
    }
    private void showDisplaySettings(){
        int[] rates={24,30,60};
        android.content.SharedPreferences prefs=getSharedPreferences("game-display",MODE_PRIVATE);
        int rate=prefs.getInt("frameCap",30);
        String[] choices={"24 FPS · lower load","30 FPS · balanced","60 FPS · higher load"};
        new android.app.AlertDialog.Builder(this).setTitle("Frame limit · next game start")
            .setSingleChoiceItems(choices,rate==24?0:rate==60?2:1,(d,i)->{
                prefs.edit().putInt("frameCap",rates[i]).apply(); d.dismiss();
            }).setNegativeButton("Cancel",null).show();
    }
    private void showGameSettings(){
        if(gamePanel==null || gameSettings!=null)return;
        String limit="Frame limit · "+boundGame.presentation().frameCap()+" FPS this session";
        java.util.List<String> items=new ArrayList<>(java.util.Arrays.asList(limit,"Open keyboard","Session details",
                "Export support bundle","Reset gear position","Stop session"));
        if(service!=null && service.forceStopAvailable())items.add("Force stop · unsaved state may be lost");
        android.app.AlertDialog dialog=new android.app.AlertDialog.Builder(this).setTitle("Game settings")
            .setItems(items.toArray(new String[0]),(d,i)->{
                if(gamePanel==null)return;
                switch(i){
                case 0: showDisplaySettings();break;
                case 1: gamePanel.requestKeyboard();break;
                case 2:
                    new android.app.AlertDialog.Builder(this).setTitle("Local session")
                        .setMessage(gamePanel.inputStatus()+"\n\n"+service.status())
                        .setPositiveButton("Return",null).show();break;
                case 3: if(service.supportExportAvailable())chooseExport();else
                    android.widget.Toast.makeText(this,"Wait for the current operation to finish.",android.widget.Toast.LENGTH_SHORT).show();break;
                case 4: gear.resetPosition();break;
                case 5: gamePanel.requestStop();break;
                case 6: if(service.forceStopAvailable())startService(new Intent(this,SessionService.class).setAction(SessionService.FORCE_STOP));break;
                default: break;
                }
            }).setNegativeButton("Return to game",null).create();
        gameSettings=dialog;
        dialog.setOnDismissListener(d->gameSettings=null);
        dialog.show();
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
