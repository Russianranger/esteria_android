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
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.runtime.RuntimeSetup;
import io.github.russianranger.esteria.runtime.ServerRuntimeSetup;
import io.github.russianranger.esteria.runtime.GuestBridgeSetup;
import io.github.russianranger.esteria.runtime.ClientRuntimeSetup;
import io.github.russianranger.esteria.runtime.ClientLaunchSetup;
import io.github.russianranger.esteria.runtime.ShaderToolsSetup;

/** Foreground owner of large import jobs. Runtime launch remains gated until qualified binaries exist. */
public final class SessionService extends Service {
    static final String IMPORT = "io.github.russianranger.esteria.IMPORT";
    static final String CANCEL = "io.github.russianranger.esteria.CANCEL";
    static final String EXPORT = "io.github.russianranger.esteria.EXPORT";
    static final String START = "io.github.russianranger.esteria.START";
    static final String PREPARE_RUNTIME = "io.github.russianranger.esteria.PREPARE_RUNTIME";
    static final String PREPARE_SERVER_RUNTIME = "io.github.russianranger.esteria.PREPARE_SERVER_RUNTIME";
    static final String ACCEPT_UI = "io.github.russianranger.esteria.ACCEPT_UI";
    static final String KEEP_UI = "io.github.russianranger.esteria.KEEP_UI";
    static final String UI_REVIEW_DIGEST = "uiReviewDigest";
    private static final String CHANNEL = "esteria-session";
    private static final int NOTIFICATION = 1001;
    final class LocalBinder extends Binder { SessionService service() { return SessionService.this; } }
    private final IBinder binder = new LocalBinder();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final AtomicBoolean busy = new AtomicBoolean();
    private final Handler main = new Handler(Looper.getMainLooper());
    private boolean destroyed;
    private int latestStartId;
    private volatile String status = "Ready to import your 3.3.5a build 12340 client folder or ZIP.";
    private volatile SafTreeSource activeFolderSource;
    // Ephemeral decisions are never restored as approval after service/process recreation.
    private volatile ClientLaunchSetup.UiReview pendingUiReview;
    private Path root;
    String status() { return status; }
    boolean busy() { return busy.get(); }
    ClientLaunchSetup.UiReview uiReview() { return pendingUiReview; }
    @Override public IBinder onBind(Intent intent) { return binder; }
    @Override public void onCreate() {
        super.onCreate();
        try {
            root = getFilesDir().getCanonicalFile().toPath();
            Files.createDirectories(root.resolve("state/logs"));
            if (getSharedPreferences("session", MODE_PRIVATE).getBoolean("interrupted", false)) {
                String action = getSharedPreferences("session", MODE_PRIVATE).getString("operationAction", "");
                status = isRuntimeSetup(action) ? setupPaused(action, true)
                        : "Previous operation was interrupted. Select the same folder or archive to resume where source metadata permits. Existing game data remains active.";
            }
            else if (new GameDataImporter(root.resolve("game")).resolveCurrent() != null)
                status = "Client data is imported. Local runtime qualification is still pending.";
        } catch (IOException e) { status = "Storage unavailable: " + e.getMessage(); }
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Local game and imports", NotificationManager.IMPORTANCE_LOW));
    }
    @SuppressLint("ApplySharedPref") // The recovery marker must be durable before touching imported data.
    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        latestStartId = startId;
        if (intent == null) { stopSelf(startId); return START_NOT_STICKY; }
        if (CANCEL.equals(intent.getAction())) {
            if (busy.get()) { requestCancellation(); status = "Stopping at a safe point…"; }
            else stopSelf(startId);
            return START_NOT_STICKY;
        }
        // A repeated startForegroundService call still requires a foreground response.
        foreground("Preparing Esteria");
        if (!busy.compareAndSet(false, true)) return START_NOT_STICKY;
        cancelled.set(false);
        String operationId = UUID.randomUUID().toString();
        getSharedPreferences("session", MODE_PRIVATE).edit().putString("operation", operationId)
                .putString("operationAction", intent.getAction()).putBoolean("interrupted", true).commit();
        worker.execute(() -> {
            try {
                if (root == null) throw new IOException("App storage is unavailable");
                if (IMPORT.equals(intent.getAction())) importData(intent);
                else if (EXPORT.equals(intent.getAction())) exportBundle(intent.getData());
                else if (START.equals(intent.getAction())) checkLaunch();
                else if (PREPARE_RUNTIME.equals(intent.getAction())) prepareRuntime();
                else if (PREPARE_SERVER_RUNTIME.equals(intent.getAction())) prepareServerRuntime();
                else if (ACCEPT_UI.equals(intent.getAction())) acceptUiReview(intent.getStringExtra(UI_REVIEW_DIGEST));
                else if (KEEP_UI.equals(intent.getAction())) keepCurrentUi(intent.getStringExtra(UI_REVIEW_DIGEST));
                else throw new IOException("Unknown operation");
            } catch (ClientLaunchSetup.ReviewRequired review) {
                pendingUiReview=review.review;
                status="Review the imported UI changes below. Your current UI and saved variables are retained.";
                log("UI review pending digest="+review.review.digest+" currentChanges="+review.review.currentChanges
                        +" candidateChanges="+review.review.candidateChanges+" conflicts="+review.review.conflicts);
            } catch (RuntimeWork.CancelledException e) {
                status = setupPaused(intent.getAction(), false);
                log("Runtime setup paused");
            } catch (GameDataImporter.ImportCancelledException e) {
                status = "Import paused. Select the same folder or archive to resume where source metadata permits; existing game data is unchanged.";
                log("Import paused");
            } catch (Exception e) {
                status = cancelled.get() ? "Operation cancelled. Existing game data remains active."
                        : e.getClass().getSimpleName() + ": " + e.getMessage();
                log(status);
            } finally {
                // Serialize completion with onStartCommand. Publishing idle before stopSelf
                // could otherwise cancel a newly queued import. A replaced service instance
                // may own a newer recovery marker; never clear that instance's operation.
                main.post(() -> {
                    if (operationId.equals(getSharedPreferences("session", MODE_PRIVATE).getString("operation", "")))
                        getSharedPreferences("session", MODE_PRIVATE).edit().putBoolean("interrupted", false).commit();
                    if (!destroyed) { stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(latestStartId); }
                    busy.set(false);
                });
            }
        });
        return START_NOT_STICKY;
    }
    private void importData(Intent intent) throws Exception {
        Uri uri = intent.getData();
        if (uri == null) throw new IOException("No source selected");
        GameDataImporter.ImportKind kind = intent.getBooleanExtra("overlay", false)
                ? GameDataImporter.ImportKind.CONTENT_OVERLAY : GameDataImporter.ImportKind.BASE_CLIENT;
        pendingUiReview=null;
        GameDataImporter importer = new GameDataImporter(root.resolve("game"));
        GameDataImporter.Result result;
        if (intent.getBooleanExtra("folder", false)) {
            status = "Reading selected folder…";
            try (SafTreeSource source = new SafTreeSource(getContentResolver(), uri, cancelled, (files, directories, reliableTimes) ->
                    status = "Reading folder: " + files + " files, " + directories + " folders"
                            + (reliableTimes ? "" : "\nThis provider omits modification times; interrupted imports must start a new copy."))) {
                activeFolderSource = source;
                result = importer.importSource(source, kind, (path, bytes, total, count, files) ->
                        status = importProgress(path, bytes, total, count, files)
                                + (source.hasReliableFileTimes() ? "" : "\nResume is unavailable for this source because some files have no modification time."), cancelled::get);
            } finally { activeFolderSource = null; }
        } else {
            Path archive = UriStager.stage(getContentResolver(), uri, root.resolve("imports"), cancelled,
                    (copied, total) -> status = "Copying archive: " + mib(copied) + (total >= 0 ? " / " + mib(total) : "") + " MiB");
            result = importer.importZip(archive, kind, (path, bytes, total, count, files) ->
                    status = importProgress(path, bytes, total, count, files), cancelled::get);
            // Delete only the temporary ZIP after the importer has published a complete generation.
            Files.deleteIfExists(archive);
        }
        status = "Import complete: " + result.copiedFiles + " copied, " + result.reusedFiles + " resumed.\nBuild 12340 base checks passed; full Esteria content and runtime are not yet qualified.";
        log("Import complete generation=" + result.generation + " copied=" + result.copiedFiles + " reused=" + result.reusedFiles);
    }
    private void checkLaunch() throws Exception {
        if (new GameDataImporter(root.resolve("game")).resolveCurrent() == null) throw new IOException("Import a build 12340 client first");
        Properties runtime = new Properties();
        try (InputStream input = getAssets().open("runtime.properties")) { runtime.load(input); }
        if (!"true".equals(runtime.getProperty("qualified")))
            throw new IOException(runtime.getProperty("reason", "No qualified local runtime is installed"));
        // A true manifest alone cannot establish a working runtime. Implement and qualify the
        // platform session adapter before admitting any runtime to this build.
        throw new IOException("This build has no qualified client/server session adapter");
    }
    private void prepareRuntime() throws IOException {
        pendingUiReview=null;
        status = "Preparing client runtime…";
        RuntimeSetup setup = new RuntimeSetup(this, root);
        GuestBridgeSetup bridges = BuildConfig.GUEST_BRIDGES_PACKAGED ? new GuestBridgeSetup(this, root) : null;
        if (bridges != null) bridges.requireWineArchive(setup.archiveSha256());
        ClientRuntimeSetup client = BuildConfig.CLIENT_RUNTIME_PACKAGED ? new ClientRuntimeSetup(this, root) : null;
        if (client != null) client.requireWineArchive(setup.archiveSha256());
        ShaderToolsSetup shaders = BuildConfig.SHADER_TOOLS_PACKAGED ? new ShaderToolsSetup(this, root) : null;
        if (shaders != null) shaders.requireWineArchive(setup.archiveSha256());
        final long[] lastUpdate = {0};
        RuntimeInstaller.Result result = setup.prepare((phase, path, completed, total) -> {
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
        if (client != null) {
            status = "Preparing reconstructed client files…";
            RuntimeInstaller.Result installed = client.prepare((phase, path, completed, total) -> {
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
            prepareClientView(client,null);
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
        status = "Preparing bundled database and server dependencies…";
        ServerRuntimeSetup setup = new ServerRuntimeSetup(this, root);
        if (setup.current() != null) {
            status = "Database and server dependencies are already prepared. Local server startup is still under development.";
            return;
        }
        final long[] lastUpdate = {0};
        RuntimeInstaller.Result result = setup.prepare((phase, path, completed, total) -> {
            long now = android.os.SystemClock.elapsedRealtime();
            if (now - lastUpdate[0] >= 250 || completed == total) {
                lastUpdate[0] = now;
                status = "Preparing database and server dependencies…\n" + mib(completed)
                        + (total >= 0 ? " / " + mib(total) : "") + " MiB"
                        + (path == null || path.isEmpty() ? "" : "\n" + path);
            }
        }, cancelled::get);
        status = "Database and server dependencies are prepared. Local server startup is still under development.";
        log("Server dependencies prepared generation=" + result.generation + " reusedFiles=" + result.reusedFiles
                + " copiedBytes=" + result.copiedBytes + " hardLinkCopies=" + result.hardLinkCopies
                + " hardLinkCopyBytes=" + result.hardLinkCopyBytes + " directorySyncSupported=" + result.directorySyncSupported
                + " mysqlVersion=" + setup.expectedMysqlVersion() + " gameRuntimeQualified=false");
    }
    private void exportBundle(Uri destination) throws Exception {
        if (destination == null || !"content".equals(destination.getScheme())) throw new IOException("No export destination selected");
        String previousStatus = status; status = "Writing support bundle…";
        Map<String, String> facts = new LinkedHashMap<>();
        facts.put("app.id", BuildConfig.APPLICATION_ID); facts.put("app.version", BuildConfig.VERSION_NAME);
        facts.put("app.sourceRevision", BuildConfig.SOURCE_REVISION);
        facts.put("buildPin.client", BuildConfig.CLIENT_REVISION); facts.put("buildPin.server", BuildConfig.SERVER_REVISION);
        facts.put("app.versionCode", String.valueOf(BuildConfig.VERSION_CODE));
        facts.put("android.api", String.valueOf(Build.VERSION.SDK_INT)); facts.put("android.release", Build.VERSION.RELEASE);
        facts.put("device.model", Build.MODEL); facts.put("device.manufacturer", Build.MANUFACTURER);
        facts.put("device.abis", android.text.TextUtils.join(",", Build.SUPPORTED_ABIS));
        facts.put("status", previousStatus); facts.put("runtime.qualified", "false");
        try {
            RuntimeSetup setup = new RuntimeSetup(this, root);
            facts.put("runtime.client.archiveSha256", setup.archiveSha256());
            facts.put("runtime.client.sourcePinSha256", setup.sourcePinSha256());
            facts.put("runtime.client.expectedGeneration", setup.generation());
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
        try (OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
            if (output == null) throw new IOException("Export destination could not be opened");
            SupportBundle.write(output, facts, logs);
        }
        status = "Support bundle saved. It contains status and bounded, redacted logs; no game assets or databases.";
    }
    private void foreground(String text) {
        Intent open = new Intent(this, MainActivity.class);
        Intent cancel = new Intent(this, SessionService.class).setAction(CANCEL);
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setContentTitle("Esteria").setContentText(text).setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
                .addAction(new Notification.Action.Builder(null, "Stop", PendingIntent.getService(this, 1, cancel, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT)).build())
                .setOngoing(true).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
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
        facts.put("snapshot.scope", "launcher-process observation; not a gameplay benchmark");
        facts.put("snapshot.capturedAtEpochMs", String.valueOf(System.currentTimeMillis()));
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
        return PREPARE_RUNTIME.equals(action) || PREPARE_SERVER_RUNTIME.equals(action) || ACCEPT_UI.equals(action) || KEEP_UI.equals(action);
    }
    private static String setupPaused(String action, boolean interrupted) {
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
    @Override public void onDestroy() { destroyed = true; requestCancellation(); worker.shutdown(); super.onDestroy(); }
    @Override public void onTimeout(int startId, int foregroundServiceType) {
        requestCancellation(); status = "Android stopped this setup operation. Start it again to resume completed work where supported.";
        stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(startId);
    }
}
