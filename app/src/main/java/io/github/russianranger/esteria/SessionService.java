package io.github.russianranger.esteria;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.ActivityManager;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.Binder;
import android.os.Build;
import android.os.IBinder;
import android.os.Debug;
import android.os.PowerManager;
import android.os.Handler;
import android.os.Looper;
import android.annotation.SuppressLint;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import java.util.Iterator;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import io.github.russianranger.esteria.core.diagnostics.SupportBundle;
import io.github.russianranger.esteria.core.diagnostics.SupportLogSelection;
import io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.StockClientCompatibility;
import io.github.russianranger.esteria.core.content.ContentProfile;
import io.github.russianranger.esteria.core.importer.ContentPackageLayout;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy;
import io.github.russianranger.esteria.runtime.RuntimeSetup;
import io.github.russianranger.esteria.runtime.ServerRuntimeSetup;
import io.github.russianranger.esteria.runtime.ServerProgramsSetup;
import io.github.russianranger.esteria.runtime.ServerExtractorsSetup;
import io.github.russianranger.esteria.runtime.ServerContentSetup;
import io.github.russianranger.esteria.runtime.GuestBridgeSetup;
import io.github.russianranger.esteria.runtime.ClientRuntimeSetup;
import io.github.russianranger.esteria.runtime.ClientLaunchSetup;
import io.github.russianranger.esteria.runtime.ShaderToolsSetup;
import io.github.russianranger.esteria.runtime.TurnipSetup;
import io.github.russianranger.esteria.runtime.TurnipReadinessProbe;
import io.github.russianranger.esteria.runtime.ServerDataToolsSetup;
import io.github.russianranger.esteria.runtime.LocalWorldSetup;
import io.github.russianranger.esteria.runtime.StockClientSetup;
import io.github.russianranger.esteria.runtime.GameSession;
import io.github.russianranger.esteria.presentation.GamePresentationPanel;
import java.time.Duration;

/** Foreground owner of large import jobs. Runtime launch remains gated until qualified binaries exist. */
public final class SessionService extends Service {
    static final String IMPORT = "io.github.russianranger.esteria.IMPORT";
    static final String CANCEL = "io.github.russianranger.esteria.CANCEL";
    static final String EXPORT = "io.github.russianranger.esteria.EXPORT";
    static final String START = "io.github.russianranger.esteria.START";
    static final String PREPARE_RUNTIME = "io.github.russianranger.esteria.PREPARE_RUNTIME";
    static final String PREPARE_SERVER_RUNTIME = "io.github.russianranger.esteria.PREPARE_SERVER_RUNTIME";
    static final String PREPARE_WORLD = "io.github.russianranger.esteria.PREPARE_WORLD";
    static final String WORLD_LOCALE = "worldLocale";
    static final String FORCE_STOP = "io.github.russianranger.esteria.FORCE_STOP";
    static final String ACCEPT_UI = "io.github.russianranger.esteria.ACCEPT_UI";
    static final String KEEP_UI = "io.github.russianranger.esteria.KEEP_UI";
    static final String UI_REVIEW_DIGEST = "uiReviewDigest";
    private static final String CHANNEL = "esteria-session";
    private static final int NOTIFICATION = 1001;
    final class LocalBinder extends Binder { SessionService service() { return SessionService.this; } }
    private final IBinder binder = new LocalBinder();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ExecutorService supportWorker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean exporting = new AtomicBoolean();
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final AtomicBoolean busy = new AtomicBoolean();
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean destroyed;
    private int latestStartId;
    private volatile String status = "Ready to import your 3.3.5a build 12340 client folder or ZIP.";
    private volatile String supportStatus="";
    private volatile SafTreeSource activeFolderSource;
    private volatile ImportDiagnostics lastImport;
    private volatile ImportIoController activeImportIo;
    private volatile ImportIoController activePreparationIo;
    private volatile WorldPreparationDiagnostics lastPreparation;
    private volatile String supportLogRecoveryReason="";
    private volatile int supportLogRejected;
    private volatile int lastMemoryTrimLevel = -1;
    private volatile long lastMemoryTrimAt;
    // Ephemeral decisions are never restored as approval after service/process recreation.
    private volatile ClientLaunchSetup.UiReview pendingUiReview;
    // The worker retains this handle across every failure until all setup
    // children and their data/import leases have confirmed cleanup.
    private volatile LocalWorldSetup.Handle worldSetup;
    private volatile StockClientSetup.Handle stockSetup;
    private volatile LocalWorldSetup.Result preparedWorld;
    private volatile TurnipReadinessProbe.Handle graphicsProbe;
    private volatile Map<String,String> graphicsProbeFacts=Map.of("turnip.probe.result","not-attempted");
    private volatile String activeAction;
    private volatile GameSession.Handle game;
    private volatile GamePresentationPanel.SessionEvents gameEvents;
    private volatile boolean lastRecoveryRequired,lastClientExitAcknowledged;
    // Bounded fixed-path metadata survives service recreation and APK updates.
    // No log content, account, configuration or environment is persisted here.
    private final Map<String,Path> selectedLogs=new LinkedHashMap<>();
    private String selectedLogsEncoded="";
    private PowerManager.WakeLock operationWake;
    private long wakeRenewAfter;
    private final Runnable wakeHeartbeat=new Runnable(){public void run(){
        if(busy.get()){keepAwake();main.postDelayed(this,60*1000L);}
    }};
    private Path root;
    String status() {
        ImportIoController io = activeImportIo == null ? activePreparationIo : activeImportIo;
        String current = io == null ? status : status + "\n" + io.statusHint();
        String support=supportStatus;return support.isEmpty()?current:current+"\n"+support;
    }
    boolean busy() { return busy.get(); }
    boolean supportExportAvailable(){return !exporting.get()&&!(busy.get()&&EXPORT.equals(activeAction));}
    ClientLaunchSetup.UiReview uiReview() { return pendingUiReview; }
    GameSession.Handle game() { return game; }
    GamePresentationPanel.SessionEvents presentationEvents() { return gameEvents; }
    boolean forceStopAvailable() { GameSession.Handle owner=game;return owner!=null&&owner.needsForceStop(); }
    @Override public IBinder onBind(Intent intent) { return binder; }
    @Override public void onCreate() {
        super.onCreate();
        try {
            root = getFilesDir().getCanonicalFile().toPath();
            Files.createDirectories(root.resolve("state/logs"));
            lastImport = new ImportDiagnostics(root.resolve("state/import-last.properties"));
            lastPreparation = new WorldPreparationDiagnostics(root.resolve("state/world-preparation-last.properties"));
            try {
                String saved=getSharedPreferences("session",MODE_PRIVATE).getString("ownedSupportLogs","");
                SupportLogSelection.Recovery recovery=SupportLogSelection.recover(root,saved);
                selectedLogs.putAll(recovery.logs);selectedLogsEncoded=SupportLogSelection.encode(root,recovery.logs);
                recordLogRecovery(recovery);
            }catch(IOException|RuntimeException invalid){log("Retained support-log selection is invalid; private files were excluded");}
            if (getSharedPreferences("session", MODE_PRIVATE).getBoolean("interrupted", false)) {
                String action = getSharedPreferences("session", MODE_PRIVATE).getString("operationAction", "");
                status = START.equals(action)?"The previous local session was interrupted. Startup will check the retained database and files; export a support bundle if it fails."
                        :isRuntimeSetup(action) ? setupPaused(action, true)
                        : "Previous operation was interrupted. Select the same folder or archive to resume where source metadata permits. Existing game data remains active.";
            }
            else if (new GameDataImporter(root.resolve("game")).resolveCurrent() != null)
                status = "Client data is imported. Local runtime qualification is still pending.";
            lastRecoveryRequired=getSharedPreferences("session",MODE_PRIVATE).getBoolean("lastRecoveryRequired",false);
            lastClientExitAcknowledged=getSharedPreferences("session",MODE_PRIVATE).getBoolean("lastClientExitAcknowledged",false);
        } catch (IOException e) { status = "Storage unavailable: " + e.getMessage(); }
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Local game and imports", NotificationManager.IMPORTANCE_LOW));
        PowerManager power=getSystemService(PowerManager.class);
        if(power!=null){operationWake=power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,BuildConfig.APPLICATION_ID+":local-operation");operationWake.setReferenceCounted(false);}
    }
    @SuppressLint("ApplySharedPref") // The recovery marker must be durable before touching imported data.
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (intent == null) { stopSelf(startId); return START_NOT_STICKY; }
        if(FORCE_STOP.equals(intent.getAction())) {
            GameSession.Handle owner=game;
            if(owner!=null)try{owner.requestForceStop();status="Force stop requested. The session will require recovery checks.";}
                catch(IOException error){status=error.getMessage();}
            return START_NOT_STICKY;
        }
        if (CANCEL.equals(intent.getAction())) {
            if (busy.get()) { requestCancellation(); status = "Stopping at a safe point…"; }
            else stopSelf(startId);
            return START_NOT_STICKY;
        }
        // A repeated startForegroundService call still requires a foreground response.
        foreground("Preparing Esteria",busy.get()?activeAction:intent.getAction());
        if(EXPORT.equals(intent.getAction())&&busy.get()) {
            if(!EXPORT.equals(activeAction)&&exporting.compareAndSet(false,true))supportWorker.execute(()->{
                try{exportBundle(intent.getData());}catch(Exception error){supportStatus="Support export failed: "+error.getMessage();log(supportStatus);}
                finally{exporting.set(false);}
            });
            return START_NOT_STICKY;
        }
        if (!busy.compareAndSet(false, true)) return START_NOT_STICKY;
        activeAction=intent.getAction();
        if(!EXPORT.equals(activeAction))supportStatus="";
        cancelled.set(false);
        keepAwake();
        main.removeCallbacks(wakeHeartbeat);main.postDelayed(wakeHeartbeat,60*1000L);
        String operationId = UUID.randomUUID().toString();
        getSharedPreferences("session", MODE_PRIVATE).edit().putString("operation", operationId)
                .putString("operationAction", intent.getAction()).putBoolean("interrupted", true).commit();
        worker.execute(() -> {
            boolean fatalFailure = false;
            try {
                if (root == null) throw new IOException("App storage is unavailable");
                runOperation(intent);
            } catch (ClientLaunchSetup.ReviewRequired review) {
                pendingUiReview=review.review;
                status="Review the imported UI changes below. Your current UI and saved variables are retained.";
                log("UI review pending digest="+review.review.digest+" currentChanges="+review.review.currentChanges
                        +" candidateChanges="+review.review.candidateChanges+" conflicts="+review.review.conflicts);
            } catch (RuntimeWork.MemoryPressureException e) {
                status=e.getMessage();log(status);
            } catch (WorldPreparationDiagnostics.MemoryPause e) {
                status=e.getMessage();log(status);
            } catch (RuntimeWork.CancelledException e) {
                status = setupPaused(intent.getAction(), false);
                log("Runtime setup paused");
            } catch (GameDataImporter.ImportCancelledException e) {
                status = e instanceof GameDataImporter.ImportMemoryPressureException ? (IMPORT.equals(intent.getAction()) ? e.getMessage() : "World preparation paused because Android memory is low. Completed work and saves are retained; retry after memory recovers.")
                        : IMPORT.equals(intent.getAction()) ? "Import paused. Select the same folder or archive to resume where source metadata permits; existing game data is unchanged." : setupPaused(intent.getAction(),false);
                log("Import paused");
            } catch (Exception e) {
                if(EXPORT.equals(intent.getAction()))supportStatus="";
                status = START.equals(intent.getAction())?(lastRecoveryRequired?"The local session stopped with recovery checks required. Export the support bundle for details."
                        :"Local startup or shutdown did not complete normally: "+e.getMessage()+". Export the support bundle for details.")
                        :cancelled.get() ? "Operation cancelled. Existing game data remains active."
                        : e.getClass().getSimpleName() + ": " + e.getMessage();
                log(status + ImportDiagnostics.failure(e));
            } catch (Error fatal) {
                // An uncaught Java OOM is not orderly completion; keep recovery state.
                fatalFailure = true;
                throw fatal;
            } finally {
                // Serialize completion with onStartCommand. Publishing idle before stopSelf
                // could otherwise cancel a newly queued import. A replaced service instance
                // may own a newer recovery marker; never clear that instance's operation.
                final boolean retainRecoveryMarker = fatalFailure;
                main.post(new Runnable(){public void run(){
                    if(exporting.get()){main.postDelayed(this,200);return;}
                    if (!retainRecoveryMarker && operationId.equals(getSharedPreferences("session", MODE_PRIVATE).getString("operation", "")))
                        getSharedPreferences("session", MODE_PRIVATE).edit().putBoolean("interrupted", false).commit();
                    if (!destroyed) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(latestStartId); }
                    main.removeCallbacks(wakeHeartbeat);releaseWake();
                    busy.set(false);
                }});
            }
        });
        return START_NOT_STICKY;
    }
    private void runOperation(Intent intent)throws Exception {
        String action=intent.getAction();
        if(!isRuntimeSetup(action)){dispatchOperation(intent);return;}
        runPreparation(action,()->dispatchOperation(intent));
    }
    private interface PreparationOperation {void run()throws Exception;}
    private void runPreparation(String action,PreparationOperation operation)throws Exception {
        if(activePreparationIo!=null){operation.run();return;}
        WorldPreparationDiagnostics diagnostics=new WorldPreparationDiagnostics(root.resolve("state/world-preparation-last.properties"));
        diagnostics.begin(action);lastPreparation=diagnostics;
        ImportIoController io=null;
        try{
            ImportIoController installed=new ImportIoController(this,diagnostics,"Preparation");io=installed;activePreparationIo=installed;
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->installed.readObserved(path,offset,count,cancelled::get))){operation.run();}
            diagnostics.finish("complete",null);
        }catch(ClientLaunchSetup.ReviewRequired review){diagnostics.finish("review-required",null);throw review;}
        catch(Exception failure){diagnostics.failed(failure);throw failure;}
        finally{if(io!=null)io.recordFinal();activePreparationIo=null;}
    }
    private void dispatchOperation(Intent intent)throws Exception {
                if (IMPORT.equals(intent.getAction())) importData(intent);
                else if (EXPORT.equals(intent.getAction())) exportBundle(intent.getData());
                else if (START.equals(intent.getAction())) startLocalGame(intent.getStringExtra(WORLD_LOCALE));
                else if (PREPARE_RUNTIME.equals(intent.getAction())) prepareRuntime();
                else if (PREPARE_SERVER_RUNTIME.equals(intent.getAction())) prepareServerRuntime();
                else if (PREPARE_WORLD.equals(intent.getAction())) {
                    String locale=intent.getStringExtra(WORLD_LOCALE);
                    inspectStockClient(locale,true);
                    prepareStockRuntime(locale);prepareServerRuntime();prepareWorld(locale);
                }
                else if (ACCEPT_UI.equals(intent.getAction())) acceptUiReview(intent.getStringExtra(UI_REVIEW_DIGEST));
                else if (KEEP_UI.equals(intent.getAction())) keepCurrentUi(intent.getStringExtra(UI_REVIEW_DIGEST));
                else throw new IOException("Unknown operation");
    }
    private void preparationProgress(String phase,String path,long completed,long total){
        WorldPreparationDiagnostics diagnostics=lastPreparation;
        if(diagnostics!=null){diagnostics.phase(phase,path);diagnostics.memory();}
        LocalWorldSetup.Handle owner=worldSetup;
        if(owner!=null){rememberLogs(owner.diagnosticLogs());if(diagnostics!=null)owner.diagnosticUsage().forEach(diagnostics::child);}
        ImportIoController io=activePreparationIo;
        if(io!=null&&io.pressureLevel()>=2){if(diagnostics!=null)diagnostics.checkpoint();throw new WorldPreparationDiagnostics.MemoryPause();}
        String label=phase.startsWith("server-data")?"Preparing world data":phase.startsWith("shader")?"Preparing graphics data":"Preparing local components";
        status=label+"…"+(path==null||path.isEmpty()?"":"\n"+path);
    }
    private void importData(Intent intent) throws Exception {
        Uri uri = intent.getData();
        if (uri == null) throw new IOException("No source selected");
        GameDataImporter.ImportKind kind = intent.getBooleanExtra("overlay", false)
                ? GameDataImporter.ImportKind.CONTENT_OVERLAY : GameDataImporter.ImportKind.BASE_CLIENT;
        boolean folder = intent.getBooleanExtra("folder", false);
        ImportDiagnostics diagnostics = new ImportDiagnostics(root.resolve("state/import-last.properties"));
        lastImport = diagnostics;
        diagnostics.begin(folder ? "folder" : "zip", kind.name(), uri.getAuthority(), uri.toString(),
                folder ? "folder display name pending cancellable inventory" : "ZIP document; client root pending inspection");
        log("Import started " + diagnostics.context());
        pendingUiReview=null;
        try {
        ImportIoController io = new ImportIoController(this, diagnostics);
        activeImportIo = io;
        GameDataImporter importer = new GameDataImporter(root.resolve("game"), io.governor());
        GameDataImporter.Result result;
        if (folder) {
            status = "Reading selected folder…";
            diagnostics.phase("folder-enumeration", "not-yet-detected", "");
            try (SafTreeSource source = new SafTreeSource(getContentResolver(), uri, cancelled, (files, directories, reliableTimes) -> {
                    SafTreeSource current = activeFolderSource;
                    if (current != null && current.selectedRootName() != null) diagnostics.selectedRoot(current.selectedRootName());
                    diagnostics.memory();
                    status = "Reading folder: " + files + " files, " + directories + " folders"
                            + (reliableTimes ? "" : "\nThis provider omits modification times; interrupted imports must start a new copy."); }, io.governor(), io)) {
                activeFolderSource = source;
                result = importer.importSource(source, kind, importListener(diagnostics, source), cancelled::get);
            } finally { activeFolderSource = null; }
        } else {
            diagnostics.phase("zip-document-copy", "not-yet-detected", "");
            Path archive = UriStager.stage(getContentResolver(), uri, root.resolve("imports"), cancelled,
                    (copied, total) -> { diagnostics.memory(); status = "Copying archive: " + mib(copied) + (total >= 0 ? " / " + mib(total) : "") + " MiB"; }, io.governor(), io);
            result = importer.importZip(archive, kind, importListener(diagnostics, null), cancelled::get);
            // Delete only the temporary ZIP after the importer has published a complete generation.
            Files.deleteIfExists(archive);
        }
        diagnostics.phase("stock-compatibility");
        status = "Import complete: " + result.copiedFiles + " copied, " + result.reusedFiles + " resumed.\n"
            +inspectStockClient(getSharedPreferences("world",MODE_PRIVATE).getString("locale","enUS"),false).toText();
        diagnostics.finish("complete", null);
        log("Import complete generation=" + result.generation + " copied=" + result.copiedFiles + " reused=" + result.reusedFiles);
        } catch (GameDataImporter.ImportCancelledException paused) {
            diagnostics.finish(paused instanceof GameDataImporter.ImportMemoryPressureException ? "paused-memory" : "paused", paused);
            log("Import paused " + diagnostics.context()); throw paused;
        } catch (Exception failure) {
            diagnostics.finish("failed", failure); log("Import failed " + diagnostics.context()); throw failure;
        } finally {
            ImportIoController io = activeImportIo;
            if (io != null) io.recordFinal();
            activeImportIo = null;
        }
    }
    private GameDataImporter.ProgressListener importListener(ImportDiagnostics diagnostics, SafTreeSource source) {
        return new GameDataImporter.ProgressListener() {
            private long reportedAt;
            @Override public void onProgress(String path, long bytes, long total, int count, int files) {
                diagnostics.memory();
                long now = System.nanoTime();
                if (count != files && now - reportedAt < 200_000_000L) return;
                reportedAt = now;
                status = importProgress(path, bytes, total, count, files)
                    + (source == null || source.hasReliableFileTimes() ? "" : "\nResume is unavailable for this source because some files have no modification time.");
            }
            @Override public void onDiagnostic(String phase, String detectedRoot, String path) {
                if (source != null && source.selectedRootName() != null) diagnostics.selectedRoot(source.selectedRootName());
                diagnostics.phase(phase, detectedRoot, path);
            }
        };
    }
    private void startLocalGame(String locale) throws Exception {
        clearSelectedLogs("game.");
        if (new GameDataImporter(root.resolve("game")).resolveCurrent() == null) throw new IOException("Import a build 12340 client first");
        if(!BuildConfig.PROOT_PACKAGED||!BuildConfig.CLIENT_RUNTIME_PACKAGED||!BuildConfig.GUEST_BRIDGES_PACKAGED||
                !BuildConfig.TURNIP_PACKAGED||!BuildConfig.SERVER_RUNTIME_PACKAGED||!BuildConfig.SERVER_PROGRAMS_PACKAGED||
                !BuildConfig.SERVER_CONTENT_PACKAGED||!BuildConfig.SERVER_DATA_TOOLS_PACKAGED||!BuildConfig.SHADER_TOOLS_PACKAGED)
            throw new IOException("This build does not include the complete local game profile");
        if(locale==null)locale=getSharedPreferences("world",MODE_PRIVATE).getString("locale",null);
        if(locale==null)throw new IOException("Select the imported client language before starting");
        String selectedLocale=locale;
        runPreparation(START,()->{inspectStockClient(selectedLocale,true);prepareStockRuntime(selectedLocale);prepareServerRuntime();prepareWorld(selectedLocale);});
        if(cancelled.get())throw new RuntimeWork.CancelledException();
        LocalWorldSetup.Result setup=preparedWorld;
        if(setup==null)throw new IOException("Local world setup did not complete");
        GamePresentationPanel.SessionEvents relay=new GamePresentationPanel.SessionEvents(code->{
            cancelled.set(true);status="A local session component stopped. Export the support bundle after shutdown.";log("Game component failure="+code);
        });
        gameEvents=relay;
        GameSession.Handle owner=GameSession.begin(this,root,setup,new ClientRuntimeSetup(this,root),new GuestBridgeSetup(this,root),
            new TurnipSetup(this,root),new GameSession.Events(){
                public void frameSize(int width,int height){relay.frameSize(width,height);}
                public void failed(String code){relay.failed(code);}
                public void clientExited(int exitCode,boolean forced){cancelled.set(true);log("Client process exited code="+exitCode+" forced="+forced+" saveQualified=false");}
            });
        game=owner;lastRecoveryRequired=false;lastClientExitAcknowledged=false;
        Throwable operationFailure=null;
        try {
            owner.start((phase,path,completed,total)->{keepAwake();rememberLogs(owner.diagnosticLogs());status=phase.contains("database")?"Starting the local database…":phase.startsWith("server")?"Starting local services…":"Starting the reconstructed client…";},cancelled::get);
            rememberLogs(owner.diagnosticLogs());
            status="Local client started. Displayed login and world state have not been automatically verified.";
            while(!cancelled.get()&&owner.state()==GameSession.State.CLIENT_STARTED&&owner.isClientAlive()) {
                keepAwake();try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Session worker interrupted",error);}
            }
        }catch(IOException|RuntimeException error){operationFailure=error;throw error;}
        finally {
            rememberLogs(owner.diagnosticLogs());
            IOException cleanup=closeGame(owner);lastRecoveryRequired=owner.recoveryRequired();lastClientExitAcknowledged=owner.clientExitAcknowledged();
            if(cleanup!=null){if(operationFailure!=null)operationFailure.addSuppressed(cleanup);else throw cleanup;}
        }
        status=lastRecoveryRequired?"Session stopped. Recovery checks are required before the next launch.":"Local session stopped.";
    }
    private StockClientCompatibility.Report inspectStockClient(String locale,boolean required)throws IOException {
        Path imported=new GameDataImporter(root.resolve("game")).resolveCurrent();
        if(imported==null)throw new IOException("Import your complete ChromieCraft 3.3.5a client folder or ZIP first");
        StockClientCompatibility.Report report=StockClientCompatibility.inspect(imported,locale==null?"enUS":locale);
        log("Content profile="+ContentProfile.ID+"\n"+report.toText());
        if(required)report.requirePreparationInputs();
        return report;
    }
    private IOException closeGame(GameSession.Handle owner) {
        IOException failure=null;boolean interrupted=Thread.interrupted();
        while(owner.state()!=GameSession.State.CLOSED) {
            keepAwake();
            rememberLogs(owner.diagnosticLogs());
            try{owner.close(Duration.ofSeconds(30));}
            catch(IOException error){if(failure==null)failure=error;else if(error!=failure&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
            catch(RuntimeException error){IOException wrapped=new IOException("Game cleanup failed; ownership retained",error);if(failure==null)failure=wrapped;else if(failure.getSuppressed().length<15)failure.addSuppressed(wrapped);}
            if(owner.state()!=GameSession.State.CLOSED) {
                status=owner.needsForceStop()?"The client has not closed. You can wait, or choose Force stop; unsaved client state may be lost."
                    :"Stopping the local session. Its files remain in use until cleanup finishes…";
                try{Thread.sleep(250);}catch(InterruptedException ignored){interrupted=true;}
            }
        }
        rememberLogs(owner.diagnosticLogs());
        log("Game owner closed clientExitAcknowledged="+owner.clientExitAcknowledged()+" recoveryRequired="+owner.recoveryRequired()
            +" forced="+owner.wasForced()+" handoffRecoveryRequired="+owner.handoffRecoveryRequired()+" saveQualified=false");
        getSharedPreferences("session",MODE_PRIVATE).edit().putBoolean("lastRecoveryRequired",owner.recoveryRequired())
            .putBoolean("lastClientExitAcknowledged",owner.clientExitAcknowledged()).commit();
        game=null;if(interrupted)Thread.currentThread().interrupt();return failure;
    }
    private void prepareRuntime() throws IOException { prepareRuntime(true); }
    private void prepareStockRuntime(String locale)throws IOException {
        preparationProgress("world-client-runtime","",0,-1);
        prepareRuntime(false);
        preparationProgress("world-stock-selection","",0,-1);
        StockClientSetup.Handle owner=StockClientSetup.begin(this,root,new RuntimeSetup(this,root),new ShaderToolsSetup(this,root),locale);
        stockSetup=owner;Throwable operationFailure=null;
        try {
            owner.prepare((phase,path,completed,total)->{
                keepAwake();rememberLogs(owner.diagnosticLogs());
                preparationProgress(phase,path,completed,total);
                if(lastPreparation!=null&&owner.processAlive())lastPreparation.child("stock",owner.usage());
                status="Checking and selecting stock client content…"+(path==null||path.isEmpty()?"":"\n"+path);
            },cancelled::get);
            log("Stock client selection completed contentProfile="+ContentProfile.ID+" gameplayQualified=false");
        }catch(IOException|RuntimeException error){operationFailure=error;throw error;}
        finally {
            IOException cleanup=null;boolean interrupted=Thread.interrupted();
            while(owner.state()!=StockClientSetup.State.CLOSED) {
                keepAwake();rememberLogs(owner.diagnosticLogs());
                try{owner.close(Duration.ofSeconds(30));}
                catch(IOException error){if(cleanup==null)cleanup=error;else if(cleanup!=error&&cleanup.getSuppressed().length<15)cleanup.addSuppressed(error);}
                if(owner.state()!=StockClientSetup.State.CLOSED) {
                    status="Stopping the stock content check safely…";
                    try{Thread.sleep(250);}catch(InterruptedException ignored){interrupted=true;}
                }
            }
            rememberLogs(owner.diagnosticLogs());stockSetup=null;
            if(interrupted)Thread.currentThread().interrupt();
            if(cleanup!=null){if(operationFailure!=null)operationFailure.addSuppressed(cleanup);else throw cleanup;}
        }
        inspectStockClient(locale,true);
        prepareClientView(new ClientRuntimeSetup(this,root),null);
    }
    private void prepareRuntime(boolean prepareView) throws IOException {
        pendingUiReview=null;
        status = "Preparing client runtime…";
        RuntimeSetup setup = new RuntimeSetup(this, root);
        GuestBridgeSetup bridges = BuildConfig.GUEST_BRIDGES_PACKAGED ? new GuestBridgeSetup(this, root) : null;
        if (bridges != null) bridges.requireWineArchive(setup.archiveSha256());
        ClientRuntimeSetup client = BuildConfig.CLIENT_RUNTIME_PACKAGED ? new ClientRuntimeSetup(this, root) : null;
        if (client != null) client.requireWineArchive(setup.archiveSha256());
        ShaderToolsSetup shaders = BuildConfig.SHADER_TOOLS_PACKAGED ? new ShaderToolsSetup(this, root) : null;
        if (shaders != null) shaders.requireWineArchive(setup.archiveSha256());
        TurnipSetup graphics = BuildConfig.TURNIP_PACKAGED ? new TurnipSetup(this,root) : null;
        if (graphics != null) graphics.requireWineArchive(setup.archiveSha256());
        final long[] lastUpdate = {0};
        RuntimeInstaller.Result result = setup.prepare((phase, path, completed, total) -> {
            keepAwake();
            long now = android.os.SystemClock.elapsedRealtime();
            if (now - lastUpdate[0] >= 250 || completed == total) {
                lastUpdate[0] = now;
                status = runtimePhase(phase) + "\n" + mib(completed)
                        + (total >= 0 ? " / " + mib(total) : "") + " MiB"
                        + (path == null || path.isEmpty() ? "" : "\n" + path);
            }
        }, cancelled::get);
        status = "Client runtime files are prepared. Local services and gameplay are still under development.";
        log("Runtime prepared generation=" + result.generation + " reusedFiles=" + result.reusedFiles
                + " copiedBytes=" + result.copiedBytes + " hardLinkCopies=" + result.hardLinkCopies
                + " hardLinkCopyBytes=" + result.hardLinkCopyBytes + " directorySyncSupported=" + result.directorySyncSupported
                + " gameRuntimeQualified=false");
        if (bridges != null) {
            status = "Preparing display, input and audio support…";
            RuntimeInstaller.Result support = bridges.prepare((phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing display, input and audio support…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB";
                }
            }, cancelled::get);
            log("Guest bridges prepared generation=" + support.generation + " reusedFiles=" + support.reusedFiles
                    + " copiedBytes=" + support.copiedBytes + " archiveSha256=" + bridges.archiveSha256()
                    + " gameRuntimeQualified=false");
        }
        if (shaders != null) {
            status = "Preparing offline shader tools…";
            RuntimeInstaller.Result installed = shaders.prepare((phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing offline shader tools…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB";
                }
            }, cancelled::get);
            log("Shader tools prepared generation=" + installed.generation + " revision=" + shaders.revision()
                    + " reusedFiles=" + installed.reusedFiles + " copiedBytes=" + installed.copiedBytes
                    + " archiveSha256=" + shaders.archiveSha256() + " gameAssetShadersQualified=false");
        }
        if (graphics != null) {
            status="Preparing graphics support…";
            RuntimeInstaller.Result installed=graphics.prepare((phase,path,completed,total)->
                status="Preparing graphics support…\n"+mib(completed)+(total>=0?" / "+mib(total):"")+" MiB",cancelled::get);
            log("Graphics provider prepared generation="+installed.generation+" archiveSha256="+graphics.archiveSha256()
                +" hardwareQualified=false");
        }
        if (client != null) {
            status = "Preparing reconstructed client files…";
            RuntimeInstaller.Result installed = client.prepare((phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing reconstructed client files…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB";
                }
            }, cancelled::get);
            log("Reconstructed client prepared generation=" + installed.generation + " revision=" + client.sourceRevision()
                    + " build=" + client.buildId() + " reusedFiles=" + installed.reusedFiles
                    + " copiedBytes=" + installed.copiedBytes + " gameRuntimeQualified=false");
            if(prepareView)prepareClientView(client,null);
        }
        status = "Client runtime files are prepared. Local services and gameplay are still under development.";
    }
    /** All setup operations share the service worker; START remains gated, so the client is stopped.
     * A future gameplay adapter must hold the stopped-session guard across this complete call.
     */
    private void prepareClientView(ClientRuntimeSetup client,String acceptedDigest) throws IOException {
        status="Preparing persistent client settings and launch files…";
        final long[] lastUpdate={0};
        ClientLaunchSetup.Prepared prepared=ClientLaunchSetup.prepare(this,root,client,acceptedDigest,(phase,path,completed,total)-> {
            long now=android.os.SystemClock.elapsedRealtime();
            if(now-lastUpdate[0]>=250||completed==total) {
                lastUpdate[0]=now;
                status="client-ui-assessing".equals(phase) ? "Checking changes in writable UI files…"
                        : "Preparing persistent client settings and launch files…";
            }
        },cancelled::get);
        if(prepared!=null)log("Client view prepared generation="+prepared.view.generation+" reusedExecutables="
                +prepared.view.reusedExecutables+" gameRuntimeQualified=false");
        pendingUiReview=null;
    }
    private ClientLaunchSetup.UiReview requireDisplayedReview(String digest) throws IOException {
        ClientLaunchSetup.UiReview pending=pendingUiReview;
        if(digest==null||pending==null||!pending.digest.equals(digest))
            throw new IOException("The UI review is no longer current. Prepare client runtime to get a new report.");
        return pending;
    }
    private void acceptUiReview(String digest) throws IOException {
        requireDisplayedReview(digest);
        if(!BuildConfig.CLIENT_RUNTIME_PACKAGED)throw new IOException("This build has no packaged reconstructed client");
        pendingUiReview=null;
        // This path uses already prepared binaries; it does not redownload or rescan the Wine archive.
        prepareClientView(new ClientRuntimeSetup(this,root),digest);
        status="Imported UI version selected. Previous UI files and saved variables are retained. Gameplay remains under development.";
        log("Reviewed UI version selected; previous generations retained; gameRuntimeQualified=false");
    }
    private void keepCurrentUi(String digest) throws IOException {
        requireDisplayedReview(digest);
        pendingUiReview=null;
        status="Current UI retained. The newly imported content is not ready to launch with that UI. Choose Prepare client runtime to review again.";
        log("UI review dismissed; existing UI pointer preserved");
    }
    private void prepareServerRuntime() throws IOException {
        preparationProgress("world-server-runtime","",0,-1);
        status = "Preparing bundled database and server dependencies…";
        ServerRuntimeSetup setup = new ServerRuntimeSetup(this, root);
        ServerProgramsSetup programs = BuildConfig.SERVER_PROGRAMS_PACKAGED ? new ServerProgramsSetup(this, root) : null;
        ServerContentSetup content = BuildConfig.SERVER_CONTENT_PACKAGED ? new ServerContentSetup(this, root) : null;
        ServerExtractorsSetup extractors = BuildConfig.SERVER_EXTRACTORS_PACKAGED ? new ServerExtractorsSetup(this, root) : null;
        ServerDataToolsSetup dataTools = BuildConfig.SERVER_DATA_TOOLS_PACKAGED ? new ServerDataToolsSetup(this,root) : null;
        // Validate the complete selected pair before either installation can change its pointer.
        if (programs != null) programs.requireServerRuntimeArchive(setup.archiveSha256());
        if (content != null) content.requireServerRuntimeArchive(setup.archiveSha256());
        if (extractors != null) extractors.requireServerRuntimeArchive(setup.archiveSha256());
        if (dataTools != null) dataTools.requireServerRuntimeArchive(setup.archiveSha256());
        final long[] lastUpdate = {0};
        // prepare() reuses a verified dependency generation without opening its archive.
        // Continue after reuse so an app update can add a new programs generation.
        RuntimeInstaller.Result result = setup.prepare((phase, path, completed, total) -> {
            keepAwake();
            long now = android.os.SystemClock.elapsedRealtime();
            if (now - lastUpdate[0] >= 250 || completed == total) {
                lastUpdate[0] = now;
                status = "Preparing database and server dependencies…\n" + mib(completed)
                        + (total >= 0 ? " / " + mib(total) : "") + " MiB"
                        + (path == null || path.isEmpty() ? "" : "\n" + path);
            }
        }, cancelled::get);
        log("Server dependencies prepared generation=" + result.generation + " reusedFiles=" + result.reusedFiles
                + " copiedBytes=" + result.copiedBytes + " hardLinkCopies=" + result.hardLinkCopies
                + " hardLinkCopyBytes=" + result.hardLinkCopyBytes + " directorySyncSupported=" + result.directorySyncSupported
                + " mysqlVersion=" + setup.expectedMysqlVersion() + " gameRuntimeQualified=false");
        if (programs != null) {
            status = "Preparing bundled server programs…";
            RuntimeInstaller.Result installed = programs.prepare(setup.archiveSha256(), (phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing bundled server programs…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB"
                            + (path == null || path.isEmpty() ? "" : "\n" + path);
                }
            }, cancelled::get);
            log("Server programs prepared generation=" + installed.generation + " revision=" + BuildConfig.SERVER_PROGRAMS_REVISION
                    + " archiveSha256=" + programs.archiveSha256() + " sourcePinSha256=" + BuildConfig.SERVER_PROGRAMS_PIN
                    + " reusedFiles=" + installed.reusedFiles + " copiedBytes=" + installed.copiedBytes
                    + " androidRuntimeQualified=false gameRuntimeQualified=false");
        }
        if (content != null) {
            status = "Preparing bundled server data…";
            RuntimeInstaller.Result installed = content.prepare(setup.archiveSha256(), (phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing bundled server data…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB";
                }
            }, cancelled::get);
            log("Server source content prepared generation=" + installed.generation
                    + " archiveSha256=" + content.archiveSha256() + " receiptSha256=" + content.receiptSha256()
                    + " reusedFiles=" + installed.reusedFiles + " copiedBytes=" + installed.copiedBytes
                    + " schemaInitialized=false gameRuntimeQualified=false");
        }
        if (extractors != null) {
            status = "Preparing bundled data tools…";
            RuntimeInstaller.Result installed = extractors.prepare(setup.archiveSha256(), (phase, path, completed, total) -> {
                keepAwake();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastUpdate[0] >= 250 || completed == total) {
                    lastUpdate[0] = now;
                    status = "Preparing bundled data tools…\n" + mib(completed)
                            + (total >= 0 ? " / " + mib(total) : "") + " MiB";
                }
            }, cancelled::get);
            log("Server extractors prepared generation=" + installed.generation + " archiveSha256=" + extractors.archiveSha256()
                    + " reusedFiles=" + installed.reusedFiles + " copiedBytes=" + installed.copiedBytes
                    + " clientDataConverted=false customDataLoadOrderQualified=false androidRuntimeQualified=false");
        }
        if(dataTools!=null) {
            status="Preparing world data tools…";
            RuntimeInstaller.Result installed=dataTools.prepare(setup.archiveSha256(),(phase,path,completed,total)->
                status="Preparing world data tools…\n"+mib(completed)+(total>=0?" / "+mib(total):"")+" MiB",cancelled::get);
            log("Composed data tools prepared generation="+installed.generation+" archiveSha256="+dataTools.archiveSha256()
                +" clientDataConverted=false worldQualified=false");
        }
        status = programs == null
                ? "Database and server dependencies are prepared. Local server startup is still under development."
                : "Database dependencies and server programs are prepared. Local server startup is still under development.";
    }
    private void prepareWorld(String locale)throws IOException {
        // Keep the previous fixed logs until a replacement owner supplies its paths.
        preparationProgress("world-admission","",0,-1);
        if(locale==null||!java.util.Set.of("deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU").contains(locale))
            throw new IOException("Select the language of the imported client before preparing the world");
        if(!BuildConfig.SERVER_RUNTIME_PACKAGED||!BuildConfig.SERVER_PROGRAMS_PACKAGED||!BuildConfig.SERVER_CONTENT_PACKAGED||
                !BuildConfig.SERVER_DATA_TOOLS_PACKAGED||!BuildConfig.SHADER_TOOLS_PACKAGED)
            throw new IOException("This build does not include the complete source-qualified local world setup profile");
        preparedWorld=null;pendingUiReview=null;
        ServerRuntimeSetup server=new ServerRuntimeSetup(this,root);
        ServerProgramsSetup programs=new ServerProgramsSetup(this,root);
        ServerContentSetup content=new ServerContentSetup(this,root);
        ServerDataToolsSetup tools=new ServerDataToolsSetup(this,root);
        RuntimeSetup wine=new RuntimeSetup(this,root);ShaderToolsSetup shaders=new ShaderToolsSetup(this,root);
        preparationProgress("world-graphics-check","",0,-1);
        if(BuildConfig.TURNIP_PACKAGED)verifyGraphics(wine,new TurnipSetup(this,root));
        status="Preparing the local world. Completed data is reused when its inputs match…";
        // Four GiB is a conservative free-space policy for fresh database work,
        // separate from imported/extracted assets; no device footprint claim.
        LocalWorldSetup.Handle owner=LocalWorldSetup.begin(this,root,server,programs,content,tools,wine,shaders,locale,1,4L<<30,this::preparationProgress);
        worldSetup=owner;
        Throwable operationFailure=null;LocalWorldSetup.Result result;
        try {
            result=owner.prepare((phase,path,completed,total)->{keepAwake();preparationProgress(phase,path,completed,total);},cancelled::get);
            log("World setup completed dataGeneration="+result.data.generation+" shaders="+result.shaders.generation
                +" installation="+result.installation.slotId+" reusedInstallation="+result.reusedInstallation
                +" worldQualified=false gameplayQualified=false");
        }catch(IOException|RuntimeException error){operationFailure=error;throw error;}
        finally {
            rememberLogs(owner.diagnosticLogs());
            IOException cleanup=closeWorldSetup(owner);
            if(cleanup!=null){if(operationFailure!=null)operationFailure.addSuppressed(cleanup);else throw cleanup;}
        }
        preparedWorld=result;
        getSharedPreferences("world",MODE_PRIVATE).edit().putString("locale",locale).apply();
        status="World data, shaders and the local database are prepared. World entry has not yet been validated.";
    }
    /** Explicit setup checks the installed driver before lengthy extraction or
     * SQL. The Service keeps cleanup ownership and logs through cancellation. */
    private void verifyGraphics(RuntimeSetup wine,TurnipSetup graphics)throws IOException {
        graphicsProbeFacts=Map.of("turnip.probe.result","pending","turnip.probe.gameplayQualified","false");
        TurnipReadinessProbe.Handle owner;
        try {
            TurnipReadinessProbe.Handle prior=TurnipReadinessProbe.pendingCleanup(this);
            if(prior!=null) {
                graphicsProbe=prior;
                IOException cleanup=closeGraphicsProbe(prior);
                if(cleanup!=null)throw cleanup;
            }
            owner=TurnipReadinessProbe.begin(this,wine,graphics);
        }catch(IOException|RuntimeException error){
            graphicsProbeFacts=Map.of("turnip.probe.result","not-started","turnip.probe.failureStage","admission-or-prior-cleanup",
                "turnip.probe.gameplayQualified","false");
            throw error;
        }
        graphicsProbe=owner;Throwable operationFailure=null;
        try {
            status="Checking graphics support…";
            rememberLogs(owner.diagnosticLogs());
            TurnipReadinessProbe.Result result=owner.run((phase,path,completed,total)->keepAwake(),cancelled::get);
            graphicsProbeFacts=result.diagnosticFacts();
            log("Graphics component readback passed deviceId="+result.deviceId+" elapsedMillis="+result.elapsedMillis
                +" driverGeneration="+result.driverGeneration+" wineGeneration="+result.wineGeneration+" gameplayQualified=false");
        }catch(IOException|RuntimeException error){
            graphicsProbeFacts=Map.of("turnip.probe.result","failed","turnip.probe.gameplayQualified","false");
            operationFailure=error;throw error;
        }finally {
            IOException cleanup=closeGraphicsProbe(owner);
            if(cleanup!=null){if(operationFailure!=null)operationFailure.addSuppressed(cleanup);else throw cleanup;}
        }
    }
    private IOException closeGraphicsProbe(TurnipReadinessProbe.Handle owner) {
        IOException failure=null;boolean interrupted=Thread.interrupted();
        while(owner.state()!=TurnipReadinessProbe.State.CLOSED) {
            keepAwake();rememberLogs(owner.diagnosticLogs());
            try{owner.close(Duration.ofSeconds(2));}
            catch(IOException error){if(failure==null)failure=error;else if(failure!=error&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
            catch(RuntimeException error){IOException wrapped=new IOException("Graphics cleanup failed; ownership retained",error);
                if(failure==null)failure=wrapped;else if(failure.getSuppressed().length<15)failure.addSuppressed(wrapped);}
            if(owner.state()!=TurnipReadinessProbe.State.CLOSED) {
                status="Stopping the graphics check safely…";
                try{Thread.sleep(100);}catch(InterruptedException ignored){interrupted=true;}
            }
        }
        rememberLogs(owner.diagnosticLogs());graphicsProbe=null;
        if(interrupted)Thread.currentThread().interrupt();return failure;
    }
    /** Keep the foreground operation busy while actual cleanup is outstanding.
     * This worker is the explicit retry mechanism; no new setup/import can run. */
    private IOException closeWorldSetup(LocalWorldSetup.Handle owner) {
        IOException failure=null;boolean interrupted=Thread.interrupted();
        while(owner.state()!=LocalWorldSetup.State.CLOSED) {
            keepAwake();
            rememberLogs(owner.diagnosticLogs());
            try{owner.close(Duration.ofSeconds(20));}
            catch(IOException error){if(failure==null)failure=error;else if(failure!=error&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
            catch(RuntimeException error){IOException wrapped=new IOException("Local setup cleanup failed; ownership retained",error);
                if(failure==null)failure=wrapped;else if(failure.getSuppressed().length<15)failure.addSuppressed(wrapped);}
            if(owner.state()!=LocalWorldSetup.State.CLOSED) {
                status="Stopping local setup safely. Data remains in use until cleanup finishes…";
                try{Thread.sleep(250);}catch(InterruptedException ignored){interrupted=true;}
            }
        }
        rememberLogs(owner.diagnosticLogs());
        worldSetup=null;if(interrupted)Thread.currentThread().interrupt();return failure;
    }
    private void exportBundle(Uri destination) throws Exception {
        if (destination == null || !"content".equals(destination.getScheme())) throw new IOException("No export destination selected");
        String previousStatus = status; supportStatus = "Writing support bundle…";
        Map<String, String> facts = new LinkedHashMap<>();
        facts.put("app.id", BuildConfig.APPLICATION_ID); facts.put("app.version", BuildConfig.VERSION_NAME);
        facts.put("app.sourceRevision", BuildConfig.SOURCE_REVISION);
        facts.put("buildPin.client", BuildConfig.CLIENT_REVISION); facts.put("buildPin.server", BuildConfig.SERVER_REVISION);
        facts.put("app.versionCode", String.valueOf(BuildConfig.VERSION_CODE));
        facts.put("content.profile",ContentProfile.ID);
        facts.put("content.label",ContentProfile.LABEL);
        try { facts.put("content.compatibility",inspectStockClient(getSharedPreferences("world",MODE_PRIVATE).getString("locale","enUS"),false).toText()); }
        catch(IOException failure){facts.put("content.compatibility",failure.getMessage());}
        facts.put("android.api", String.valueOf(Build.VERSION.SDK_INT)); facts.put("android.release", Build.VERSION.RELEASE);
        facts.put("device.model", Build.MODEL); facts.put("device.manufacturer", Build.MANUFACTURER);
        facts.put("device.abis", android.text.TextUtils.join(",", Build.SUPPORTED_ABIS));
        facts.put("status", previousStatus); facts.put("runtime.qualified", "false");
        facts.put("operation.busy", Boolean.toString(busy.get()));
        facts.put("operation.action", activeAction == null ? "none" : activeAction);
        if (Build.VERSION.SDK_INT >= 29) facts.put("operation.foregroundServiceType", Integer.toString(getForegroundServiceType()));
        facts.putAll(ProcessExitDiagnostics.collect(this));
        ImportDiagnostics importDiagnostic = lastImport;
        if (importDiagnostic != null) facts.putAll(importDiagnostic.facts());
        WorldPreparationDiagnostics preparationDiagnostic=lastPreparation;
        if(preparationDiagnostic!=null)facts.putAll(preparationDiagnostic.facts());
        facts.put("support.ownedLogsRejected",Integer.toString(supportLogRejected));
        facts.put("support.ownedLogsRecoveryReason",supportLogRecoveryReason);
        GameSession.Handle gameOwner=game;
        facts.put("game.retained",Boolean.toString(gameOwner!=null));
        facts.put("game.lastRecoveryRequired",Boolean.toString(lastRecoveryRequired));
        facts.put("game.lastClientExitAcknowledged",Boolean.toString(lastClientExitAcknowledged));
        facts.put("game.characterSaveQualified","false");
        try {
            Path imported=new GameDataImporter(root.resolve("game")).resolveCurrent();
            ContentPackageLayout.ServerManifest supplied=imported==null?null:ContentPackageLayout.inspectServerManifest(imported);
            facts.put("import.serverData.supplied",Boolean.toString(supplied!=null));
            if(supplied!=null){facts.put("import.serverData.mode",supplied.mode);
                facts.put("import.serverData.manifestSha256",supplied.manifestSha256);
                facts.put("import.serverData.clientProviderOrderSha256",supplied.clientProviderOrderSha256);
                facts.put("import.serverData.provenance","user-supplied-format-checked-not-world-qualified");}
        }catch(IOException invalid){facts.put("import.serverData.selection","unavailable-or-invalid");}
        if(gameOwner!=null) {
            rememberLogs(gameOwner.diagnosticLogs());
            for(Map.Entry<String,ProcessUsageSnapshot> sample:gameOwner.usage().entrySet()) {
                ProcessUsageSnapshot usage=sample.getValue();
                facts.put("game.usage."+sample.getKey(),"scope="+usage.scope()+"; flags="+usage.flags
                    +"; visibleMembers="+usage.visibleMembers+"; scanned="+usage.scannedProcesses
                    +"; rssCoverage="+usage.rssMeasuredMembers+"; pssCoverage="+usage.pssMeasuredMembers
                    +"; cpuCoverage="+usage.cpuMeasuredMembers+"; windowNanos="+usage.durationNanos
                    +"; visibleRssBytes="+optionalMetric(usage.visibleMembersRssBytes())
                    +"; visiblePssBytes="+optionalMetric(usage.visibleMembersPssBytes())
                    +"; visibleCpuNanos="+optionalMetric(usage.visibleMembersCpuNanos())
                    +"; wholeGroupMembershipVerified=false; combinedBudgetQualified=false");
            }
            facts.put("game.state",gameOwner.state().name());
            facts.put("game.clientAlive",Boolean.toString(gameOwner.isClientAlive()));
            facts.put("game.needsExplicitForceStop",Boolean.toString(gameOwner.needsForceStop()));
            facts.put("game.recoveryRequired",Boolean.toString(gameOwner.recoveryRequired()));
            facts.put("game.handoffRecoveryRequired",Boolean.toString(gameOwner.handoffRecoveryRequired()));
            if(gameOwner.presentation()!=null) {
                long[] metrics=gameOwner.presentation().diagnostics();
                facts.put("game.presentation.ready",Long.toString(metrics[0]));
                facts.put("game.presentation.children",Long.toString(metrics[2]));
                facts.put("game.presentation.failed",Long.toString(metrics[3]));
            }
        }
        LocalWorldSetup.Handle setupOwner=worldSetup;
        StockClientSetup.Handle stockOwner=stockSetup;
        facts.put("stockSetup.retained",Boolean.toString(stockOwner!=null));
        if(stockOwner!=null){facts.put("stockSetup.state",stockOwner.state().name());rememberLogs(stockOwner.diagnosticLogs());}
        facts.put("worldSetup.retained",Boolean.toString(setupOwner!=null));
        facts.putAll(graphicsProbeFacts);
        TurnipReadinessProbe.Handle probeOwner=graphicsProbe;
        facts.put("turnip.probe.retained",Boolean.toString(probeOwner!=null));
        if(probeOwner!=null){facts.put("turnip.probe.state",probeOwner.state().name());rememberLogs(probeOwner.diagnosticLogs());}
        if(setupOwner!=null){facts.put("worldSetup.state",setupOwner.state().name());rememberLogs(setupOwner.diagnosticLogs());}
        LocalWorldSetup.Result world=preparedWorld;
        if(world!=null) {
            facts.put("worldSetup.dataGeneration",world.data.generation);
            facts.put("worldSetup.shaderGeneration",world.shaders.generation);
            facts.put("worldSetup.installationSlot",world.installation.slotId);
            facts.put("worldSetup.gameplayQualified","false");
        }
        try {
            RuntimeSetup setup = new RuntimeSetup(this, root);
            facts.put("runtime.client.archiveSha256", setup.archiveSha256());
            facts.put("runtime.client.sourcePinSha256", setup.sourcePinSha256());
            facts.put("runtime.client.expectedGeneration", setup.generation());
            facts.put("runtime.client.privatePeCopyRequested", String.valueOf(setup.wineEnvironment().containsKey("WINE_ANDROID_PRIVATE_PE_COPY")));
            facts.put("runtime.client.prepared", String.valueOf(setup.current() != null));
        } catch (IOException error) {
            facts.put("runtime.client.prepared", "false");
            facts.put("runtime.client.installationError", error.getMessage());
        }
        facts.put("runtime.server.packaged", String.valueOf(BuildConfig.SERVER_RUNTIME_PACKAGED));
        facts.put("runtime.server.prepared", "false");
        if (BuildConfig.SERVER_RUNTIME_PACKAGED) {
            try {
                ServerRuntimeSetup setup = new ServerRuntimeSetup(this, root);
                facts.put("runtime.server.archiveSha256", setup.archiveSha256());
                facts.put("runtime.server.expectedGeneration", setup.generation());
                facts.put("runtime.server.expectedMysqlVersion", setup.expectedMysqlVersion());
                facts.put("runtime.server.prepared", String.valueOf(setup.current() != null));
            } catch (IOException error) {
                facts.put("runtime.server.installationError", error.getMessage());
            }
        }
        facts.put("runtime.serverPrograms.packaged", String.valueOf(BuildConfig.SERVER_PROGRAMS_PACKAGED));
        facts.put("runtime.serverPrograms.prepared", "false");
        facts.put("runtime.serverPrograms.androidExecutionQualified", "false");
        if (BuildConfig.SERVER_PROGRAMS_PACKAGED) {
            facts.put("runtime.serverPrograms.sourceRevision", BuildConfig.SERVER_PROGRAMS_REVISION);
            facts.put("runtime.serverPrograms.sourcePinSha256", BuildConfig.SERVER_PROGRAMS_PIN);
            try {
                ServerProgramsSetup programs = new ServerProgramsSetup(this, root);
                ServerRuntimeSetup dependencies = new ServerRuntimeSetup(this, root);
                programs.requireServerRuntimeArchive(dependencies.archiveSha256());
                facts.put("runtime.serverPrograms.archiveSha256", programs.archiveSha256());
                facts.put("runtime.serverPrograms.expectedGeneration", programs.generation());
                facts.put("runtime.serverPrograms.prepared", String.valueOf(programs.current() != null));
            } catch (IOException error) {
                facts.put("runtime.serverPrograms.installationError", error.getMessage());
            }
        }
        facts.put("runtime.serverContent.packaged", String.valueOf(BuildConfig.SERVER_CONTENT_PACKAGED));
        facts.put("runtime.serverContent.prepared", "false");
        if (BuildConfig.SERVER_CONTENT_PACKAGED) {
            try {
                ServerContentSetup content = new ServerContentSetup(this, root);
                content.requireServerRuntimeArchive(new ServerRuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.serverContent.archiveSha256", content.archiveSha256());
                facts.put("runtime.serverContent.receiptSha256", content.receiptSha256());
                facts.put("runtime.serverContent.expectedGeneration", content.generation());
                facts.put("runtime.serverContent.prepared", String.valueOf(content.current() != null));
            } catch (IOException error) { facts.put("runtime.serverContent.installationError", error.getMessage()); }
        }
        facts.put("runtime.serverExtractors.packaged", String.valueOf(BuildConfig.SERVER_EXTRACTORS_PACKAGED));
        facts.put("runtime.serverExtractors.prepared", "false");
        facts.put("runtime.serverExtractors.customDataLoadOrderQualified", "false");
        if (BuildConfig.SERVER_EXTRACTORS_PACKAGED) {
            try {
                ServerExtractorsSetup tools = new ServerExtractorsSetup(this, root);
                tools.requireServerRuntimeArchive(new ServerRuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.serverExtractors.archiveSha256", tools.archiveSha256());
                facts.put("runtime.serverExtractors.sourcePinSha256", BuildConfig.SERVER_EXTRACTORS_PIN);
                facts.put("runtime.serverExtractors.expectedGeneration", tools.generation());
                facts.put("runtime.serverExtractors.prepared", String.valueOf(tools.current() != null));
            } catch (IOException error) { facts.put("runtime.serverExtractors.installationError", error.getMessage()); }
        }
        // The stock complete profile uses this composed provider independently of the historical optional extractor provider.
        facts.put("runtime.serverDataTools.packaged", String.valueOf(BuildConfig.SERVER_DATA_TOOLS_PACKAGED));
        facts.put("runtime.serverDataTools.prepared", "false");
        if (BuildConfig.SERVER_DATA_TOOLS_PACKAGED) {
            try {
                ServerDataToolsSetup tools = new ServerDataToolsSetup(this, root);
                tools.requireServerRuntimeArchive(new ServerRuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.serverDataTools.archiveSha256", tools.archiveSha256());
                facts.put("runtime.serverDataTools.sourcePinSha256", BuildConfig.SERVER_DATA_TOOLS_PIN);
                facts.put("runtime.serverDataTools.expectedGeneration", tools.packagePlan().generation);
                facts.put("runtime.serverDataTools.prepared", String.valueOf(tools.current() != null));
            } catch (IOException error) { facts.put("runtime.serverDataTools.installationError", error.getMessage()); }
        }
        facts.put("runtime.guestBridges.packaged", String.valueOf(BuildConfig.GUEST_BRIDGES_PACKAGED));
        facts.put("runtime.guestBridges.prepared", "false");
        if (BuildConfig.GUEST_BRIDGES_PACKAGED) {
            try {
                GuestBridgeSetup bridges = new GuestBridgeSetup(this, root);
                bridges.requireWineArchive(new RuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.guestBridges.archiveSha256", bridges.archiveSha256());
                facts.put("runtime.guestBridges.requiredWineArchiveSha256", bridges.requiredWineArchiveSha256());
                facts.put("runtime.guestBridges.expectedGeneration", bridges.generation());
                facts.put("runtime.guestBridges.prepared", String.valueOf(bridges.current() != null));
            } catch (IOException error) {
                facts.put("runtime.guestBridges.installationError", error.getMessage());
            }
        }
        facts.put("runtime.reconstructedClient.packaged", String.valueOf(BuildConfig.CLIENT_RUNTIME_PACKAGED));
        facts.put("runtime.reconstructedClient.prepared", "false");
        if (BuildConfig.CLIENT_RUNTIME_PACKAGED) {
            try {
                ClientRuntimeSetup client = new ClientRuntimeSetup(this, root);
                client.requireWineArchive(new RuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.reconstructedClient.archiveSha256", client.archiveSha256());
                facts.put("runtime.reconstructedClient.sourceRevision", client.sourceRevision());
                facts.put("runtime.reconstructedClient.buildId", client.buildId());
                facts.put("runtime.reconstructedClient.expectedGeneration", client.generation());
                facts.put("runtime.reconstructedClient.prepared", String.valueOf(client.current() != null));
            } catch (IOException error) {
                facts.put("runtime.reconstructedClient.installationError", error.getMessage());
            }
        }
        facts.put("runtime.shaderTools.packaged", String.valueOf(BuildConfig.SHADER_TOOLS_PACKAGED));
        facts.put("runtime.shaderTools.prepared", "false");
        if (BuildConfig.SHADER_TOOLS_PACKAGED) {
            try {
                ShaderToolsSetup shaders = new ShaderToolsSetup(this, root);
                shaders.requireWineArchive(new RuntimeSetup(this, root).archiveSha256());
                facts.put("runtime.shaderTools.archiveSha256", shaders.archiveSha256());
                facts.put("runtime.shaderTools.sourceRevision", shaders.revision());
                facts.put("runtime.shaderTools.toolManifestSha256", shaders.toolManifestSha256());
                facts.put("runtime.shaderTools.expectedGeneration", shaders.generation());
                facts.put("runtime.shaderTools.prepared", String.valueOf(shaders.current() != null));
            } catch (IOException error) {
                facts.put("runtime.shaderTools.installationError", error.getMessage());
            }
        }
        facts.put("proot.packaged", String.valueOf(BuildConfig.PROOT_PACKAGED));
        facts.put("proot.androidExecutionQualified", "false");
        if (BuildConfig.PROOT_PACKAGED) {
            JSONObject bridge = new JSONObject(readAsset("proot/build-evidence.json"));
            facts.put("proot.sourceLockSha256", bridge.getString("sourceLockSha256"));
            facts.put("proot.ndkVersion", bridge.getString("ndkVersion"));
            for (String name : new String[]{"libproot.so", "libproot-loader.so"})
                facts.put("proot.payload." + name + ".sha256", bridge.getJSONObject("payloads").getJSONObject(name).getString("sha256"));
            try {
                io.github.russianranger.esteria.runtime.InstalledProot.inspect(this);
                facts.put("proot.installedBytesVerified", "true");
            } catch (IOException error) {
                facts.put("proot.installedBytesVerified", "false");
                facts.put("proot.installationError", error.getMessage());
            }
        }
        ClientLaunchSetup.UiReview review=pendingUiReview;
        facts.put("clientUi.reviewPending",Boolean.toString(review!=null));
        if(review!=null) {
            facts.put("clientUi.reviewDigest",review.digest);
            facts.put("clientUi.currentChanges",Integer.toString(review.currentChanges));
            facts.put("clientUi.candidateChanges",Integer.toString(review.candidateChanges));
            facts.put("clientUi.conflicts",Integer.toString(review.conflicts));
        }
        addPerformanceSnapshot(facts);
        Properties runtime = new Properties();
        try (InputStream input = getAssets().open("runtime.properties")) { runtime.load(input); }
        for (String key : runtime.stringPropertyNames()) facts.put("runtime.manifest." + key, runtime.getProperty(key));
        JSONObject pins = new JSONObject(readAsset("sources.lock.json")).getJSONObject("sources");
        for (String source : new String[]{"client", "server"}) {
            JSONObject pin = pins.getJSONObject(source);
            facts.put("sourcePin." + source + ".commit", pin.getString("commit"));
            facts.put("sourcePin." + source + ".url", pin.getString("url"));
            JSONObject submodules = pin.optJSONObject("submodules");
            if (submodules != null) {
                int index = 0;
                for (Iterator<String> keys = submodules.keys(); keys.hasNext();) {
                    String path = keys.next(), prefix = "sourcePin." + source + ".submodule" + index++;
                    facts.put(prefix + ".path", path); facts.put(prefix + ".commit", submodules.getString(path));
                }
            }
        }
        Map<String, Path> logs = new LinkedHashMap<>();
        for (String name : new String[]{"launcher", "database", "authserver", "worldserver", "client"})
            logs.put(name + ".log", root.resolve("state/logs/" + name + ".log"));
        // Revalidate every selected path against current filesystem metadata at
        // export, including ancestor links. Persisted metadata grants no open lease.
        synchronized(selectedLogs) {
            try{SupportLogSelection.Recovery recovery=SupportLogSelection.recover(root,selectedLogsEncoded);logs.putAll(recovery.logs);recordLogRecovery(recovery);}
            catch(IOException invalid){facts.put("support.ownedLogs","selection-invalid-private-files-excluded");}
        }
        try (OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
            if (output == null) throw new IOException("Export destination could not be opened");
            SupportBundle.write(output, facts, logs);
        }
        supportStatus = "Support bundle saved. It contains status and bounded, redacted logs; no game assets or databases.";
    }
    private static String optionalMetric(java.util.OptionalLong value){return value.isPresent()?Long.toString(value.getAsLong()):"unavailable";}
    @SuppressLint("ApplySharedPref") // Keep fixed log selection with the retained operation's recovery state.
    private void rememberLogs(Map<String,Path> fixed) {
        synchronized(selectedLogs) {
            Map<String,Path> candidate=new LinkedHashMap<>(selectedLogs);candidate.putAll(fixed);
            if(!selectedLogsEncoded.isEmpty()&&candidate.equals(selectedLogs))return;
            try {
                SupportLogSelection.Recovery recovery=SupportLogSelection.recover(root,candidate);
                recordLogRecovery(recovery);
                String encoded=SupportLogSelection.encode(root,recovery.logs);
                if(encoded.equals(selectedLogsEncoded))return;
                selectedLogs.clear();selectedLogs.putAll(recovery.logs);selectedLogsEncoded=encoded;
                if(!getSharedPreferences("session",MODE_PRIVATE).edit().putString("ownedSupportLogs",encoded).commit())
                    log("Support-log metadata could not be retained across service recreation");
            }catch(IOException|RuntimeException invalid){log("Invalid owned support-log paths excluded");}
        }
    }
    @SuppressLint("ApplySharedPref")
    private void recordLogRecovery(SupportLogSelection.Recovery recovery){
        if(recovery.rejected<=0){
            if(supportLogRejected==0){supportLogRejected=getSharedPreferences("session",MODE_PRIVATE).getInt("ownedLogsRejected",0);supportLogRecoveryReason=getSharedPreferences("session",MODE_PRIVATE).getString("ownedLogsRecoveryReason","");}
            return;
        }
        supportLogRejected=recovery.rejected;supportLogRecoveryReason=recovery.reason;
        getSharedPreferences("session",MODE_PRIVATE).edit().putInt("ownedLogsRejected",supportLogRejected).putString("ownedLogsRecoveryReason",supportLogRecoveryReason).commit();
        log("Owned support-log recovery retained="+recovery.logs.size()+" rejected="+recovery.rejected+" reason="+recovery.reason);
    }
    private void clearSelectedLogs(String prefix) {
        synchronized(selectedLogs) {
            selectedLogs.keySet().removeIf(name->name.startsWith(prefix));
            // Force persistence even if a malformed older selection was discarded.
            selectedLogsEncoded="";rememberLogs(Map.of());
        }
    }
    private void foreground(String text,String action) {
        Intent open = new Intent(this, MainActivity.class);
        Intent cancel = new Intent(this, SessionService.class).setAction(CANCEL);
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setContentTitle("Esteria").setContentText(text).setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
                .addAction(new Notification.Action.Builder(null, "Stop", PendingIntent.getService(this, 1, cancel, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)).build())
                .setOngoing(true).build();
        if(Build.VERSION.SDK_INT>=34&&(START.equals(action)||PREPARE_WORLD.equals(action)))
            startForeground(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, notification,
            START.equals(action)||PREPARE_WORLD.equals(action)?0:ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(NOTIFICATION, notification);
    }
    private String readAsset(String name) throws IOException {
        try (InputStream input = getAssets().open(name); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] chunk = new byte[4096];
            for (int count; (count = input.read(chunk)) != -1;) {
                if (bytes.size() + count > 64 * 1024) throw new IOException("Build metadata exceeds its size limit");
                bytes.write(chunk, 0, count);
            }
            return new String(bytes.toByteArray(), StandardCharsets.UTF_8);
        }
    }
    /** Cheap observations captured only on explicit export; these are not gameplay measurements. */
    private void addPerformanceSnapshot(Map<String, String> facts) {
        facts.put("snapshot.scope", "launcher-process and Android system observation; excludes child-process PSS; not a combined gameplay benchmark");
        facts.put("snapshot.capturedAtEpochMs", String.valueOf(System.currentTimeMillis()));
        facts.put("snapshot.launcherProcess.lastTrimLevel", Integer.toString(lastMemoryTrimLevel));
        facts.put("snapshot.launcherProcess.lastTrimAtEpochMs", Long.toString(lastMemoryTrimAt));
        try {
            ActivityManager.RunningAppProcessInfo self = new ActivityManager.RunningAppProcessInfo();
            ActivityManager.getMyMemoryState(self);
            facts.put("snapshot.launcherProcess.importance", Integer.toString(self.importance));
            facts.put("snapshot.launcherProcess.importanceReasonCode", Integer.toString(self.importanceReasonCode));
        } catch (RuntimeException unavailable) { facts.put("snapshot.launcherProcess.importance", "unavailable"); }
        try {
            ActivityManager manager = getSystemService(ActivityManager.class);
            if (manager == null) facts.put("snapshot.memory.status", "unavailable");
            else {
                ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
                manager.getMemoryInfo(memory);
                facts.put("snapshot.memory.totalBytes", String.valueOf(memory.totalMem));
                facts.put("snapshot.memory.availableBytes", String.valueOf(memory.availMem));
                facts.put("snapshot.memory.lowMemory", String.valueOf(memory.lowMemory));
                facts.put("snapshot.memory.lowMemoryThresholdBytes", String.valueOf(memory.threshold));
            }
        } catch (RuntimeException unavailable) {
            facts.put("snapshot.memory.status", "unavailable: " + unavailable.getClass().getSimpleName());
        }
        try {
            Debug.MemoryInfo processMemory = new Debug.MemoryInfo();
            Debug.getMemoryInfo(processMemory);
            facts.put("snapshot.launcherProcess.pssKiB", String.valueOf(processMemory.getTotalPss()));
            facts.put("snapshot.launcherProcess.privateDirtyKiB", String.valueOf(processMemory.getTotalPrivateDirty()));
            facts.put("snapshot.launcherProcess.sharedDirtyKiB", String.valueOf(processMemory.getTotalSharedDirty()));
            Runtime vm = Runtime.getRuntime();
            facts.put("snapshot.launcherProcess.javaHeapUsedBytes", String.valueOf(vm.totalMemory() - vm.freeMemory()));
            facts.put("snapshot.launcherProcess.javaHeapLimitBytes", String.valueOf(vm.maxMemory()));
        } catch (RuntimeException unavailable) {
            facts.put("snapshot.launcherProcess.status", "unavailable: " + unavailable.getClass().getSimpleName());
        }
        try {
            if (Build.VERSION.SDK_INT < 29) facts.put("snapshot.thermal.status", "unsupported before Android API 29");
            else {
                PowerManager power = getSystemService(PowerManager.class);
                if (power == null) facts.put("snapshot.thermal.status", "unavailable");
                else {
                    int thermal = power.getCurrentThermalStatus();
                    facts.put("snapshot.thermal.androidStatusCode", String.valueOf(thermal));
                    String[] labels = {"none", "light", "moderate", "severe", "critical", "emergency", "shutdown"};
                    facts.put("snapshot.thermal.status", thermal >= 0 && thermal < labels.length ? labels[thermal] : "unknown");
                }
            }
        } catch (RuntimeException unavailable) {
            facts.put("snapshot.thermal.status", "unavailable: " + unavailable.getClass().getSimpleName());
        }
        try {
            // Android intentionally rejects Files.getFileStore; File uses statvfs.
            java.io.File storage = root.toFile();
            facts.put("snapshot.storage.freeBytes", String.valueOf(storage.getUsableSpace()));
            facts.put("snapshot.storage.totalBytes", String.valueOf(storage.getTotalSpace()));
        } catch (RuntimeException unavailable) {
            facts.put("snapshot.storage.status", "unavailable: " + unavailable.getClass().getSimpleName());
        }
    }
    private void log(String line) {
        if (root == null) return;
        try {
            Path path = root.resolve("state/logs/launcher.log");
            if (Files.exists(path) && Files.size(path) > 256 * 1024) Files.delete(path);
            Files.write(path, (System.currentTimeMillis() + " " + SupportBundle.redact(line) + "\n").getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException ignored) { }
    }
    private static long mib(long value) { return value / (1024 * 1024); }
    private static boolean isRuntimeSetup(String action) {
        return PREPARE_RUNTIME.equals(action) || PREPARE_SERVER_RUNTIME.equals(action) || PREPARE_WORLD.equals(action) || ACCEPT_UI.equals(action) || KEEP_UI.equals(action);
    }
    private static String setupPaused(String action, boolean interrupted) {
        if(START.equals(action))return "Local preparation "+(interrupted?"was interrupted":"paused")
            +". Choose Start local game to reuse completed work. Previous databases and saves are retained.";
        if(PREPARE_WORLD.equals(action))return "Local world setup "+(interrupted?"was interrupted":"paused")
            +". Choose Prepare local world to reuse completed data. Previous databases and saves are retained.";
        if(ACCEPT_UI.equals(action)||KEEP_UI.equals(action))return "UI preparation " + (interrupted ? "was interrupted" : "paused")
                + ". Prior UI generations and saved variables are retained. Choose Prepare client runtime to check the current selection and review again.";
        String label = PREPARE_SERVER_RUNTIME.equals(action) ? "Prepare server dependencies" : "Prepare client runtime";
        return "Runtime setup " + (interrupted ? "was interrupted" : "paused") + ". Choose " + label
                + " to resume; current data and saves are preserved.";
    }
    private static String runtimePhase(String phase) {
        switch (phase) {
            case "download": return "Downloading client runtime…";
            case "verify-download": case "verify-resume": return "Checking runtime download…";
            case "resume-runtime": return "Resuming prepared runtime files…";
            case "verify-runtime": return "Checking prepared runtime files…";
            case "cached": case "download-verified": return "Runtime download is ready";
            case "runtime-prepared": case "runtime-cached": return "Client runtime files are ready";
            default: return "Preparing local runtime files…";
        }
    }
    private static String importProgress(String path, long bytes, long total, int count, int files) {
        return "Importing " + count + " / " + files + " files · " + mib(bytes) + " / " + mib(total) + " MiB\n" + path;
    }
    private void requestCancellation() {
        cancelled.set(true);
        SafTreeSource source = activeFolderSource;
        if (source != null) source.cancel();
    }
    /** Bounded renewable CPU lease. Progress/monitor renew at most once a minute;
     * even a lost callback cannot leave an indefinite power lease behind. */
    private synchronized void keepAwake() {
        long now=android.os.SystemClock.elapsedRealtime();
        if(operationWake!=null&&now>=wakeRenewAfter){operationWake.acquire(10*60*1000L);wakeRenewAfter=now+60*1000L;}
    }
    private synchronized void releaseWake(){if(operationWake!=null&&operationWake.isHeld())operationWake.release();wakeRenewAfter=0;}
    @Override public void onDestroy() { destroyed = true; requestCancellation(); worker.shutdown();supportWorker.shutdown();if(!busy.get())releaseWake();super.onDestroy(); }
    @Override public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        // Observe pressure without cancelling valid work or allocating an export.
        lastMemoryTrimLevel = level; lastMemoryTrimAt = System.currentTimeMillis();
        ImportIoController io = activeImportIo;
        if (io != null) io.onTrimMemory(level);
        ImportIoController preparation=activePreparationIo;if(preparation!=null)preparation.onTrimMemory(level);
    }
    @SuppressWarnings("deprecation") // Retain Android 13 callback compatibility.
    @Override public void onLowMemory() {
        super.onLowMemory();
        ImportIoController io = activeImportIo;
        if (io != null) io.onTrimMemory(android.content.ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        ImportIoController preparation=activePreparationIo;if(preparation!=null)preparation.onTrimMemory(android.content.ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
    }
    @Override public void onTimeout(int startId, int foregroundServiceType) {
        requestCancellation(); status = "Android stopped this setup operation. Start it again to resume completed work where supported.";
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(startId);
    }
}
