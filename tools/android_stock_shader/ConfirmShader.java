package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.FutureTask;
import org.json.JSONObject;

/** Isolated package-UID observer. All installer, translator and receipt logic comes from the installed APK. */
public final class ConfirmShader {
    private static final String PACKAGE = "io.github.russianranger.esteria.stock";
    private static final String ACTOR = "qa-signed-stock-shaders";

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !(args[0].equals("cold") || args[0].equals("warm") || args[0].equals("repair"))
                || !args[1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("mode and import required");
        if (Looper.myLooper() == null) Looper.prepareMainLooper();
        Class<?> activity = Class.forName("android.app.ActivityThread");
        Object thread = activity.getMethod("systemMain").invoke(null);
        Context system = (Context)activity.getMethod("getSystemContext").invoke(thread);
        Context installed = system.createPackageContext(PACKAGE,0);
        if (android.os.Process.myUid() != installed.getApplicationInfo().uid)
            throw new IllegalStateException("Android package UID required");
        Path root = installed.getFilesDir().getCanonicalFile().toPath().resolve(ACTOR);
        Context context = new ContextWrapper(installed) {
            @Override public Context getApplicationContext() { return this; }
            @Override public File getFilesDir() { return root.toFile(); }
        };
        System.load(installed.getApplicationInfo().nativeLibraryDir + "/libesteria_process.so");
        FutureTask<Void> job = new FutureTask<>(() -> {
            if (args[0].equals("repair")) ConfirmShaderRepair.exercise(context, root, args[1]);
            else exercise(context,root,args[0].equals("cold"),args[1]);
            return null;
        });
        new Thread(job,"qa-stock-shader-owner").start();
        try {
            job.get();
        } catch (java.util.concurrent.ExecutionException failure) {
            System.err.println("ANDROID_SHADER_EXCEPTION " + failure.getCause().getClass().getName());
            throw failure;
        }
    }

    private static void exercise(Context context,Path root,boolean cold,String expectedImport) throws Exception {
        RuntimeSetup wine = new RuntimeSetup(context,root);
        ShaderToolsSetup tools = new ShaderToolsSetup(context,root);
        tools.requireWineArchive(wine.archiveSha256());
        long started = System.nanoTime();
        RuntimeWork.Progress progress = new RuntimeWork.Progress() {
            private String previous = "";
            private long last;
            public void update(String phase,String path,long done,long total) {
                long now = System.nanoTime();
                if (!previous.equals(phase) || now-last >= 60_000_000_000L) {
                    System.out.println("ANDROID_SHADER_PHASE " + phase + " " + (now-started)/1_000_000);
                    previous=phase;
                    last=now;
                }
            }
        };
        Path pointer = root.resolve("state/shader-work/shaders/current");
        if (Files.exists(pointer) == cold)
            throw new IllegalStateException("Shader pointer at entry differs from requested mode");
        try (GameSession.Leases inputs = GameSession.claim(root)) {
            RuntimeInstaller.Result installedWine = wine.prepare(progress,RuntimeWork.NEVER_CANCELLED);
            RuntimeInstaller.Result installedTools = tools.prepare(progress,RuntimeWork.NEVER_CANCELLED);
            if (installedWine.alreadyInstalled == cold || installedTools.alreadyInstalled == cold
                    || !cold && (installedWine.copiedBytes != 0 || installedTools.copiedBytes != 0))
                throw new IllegalStateException("Unexpected provider reuse or copy");
            ShaderSetup.Handle owner = ShaderSetup.begin(context,root,wine,tools,"enUS");
            ShaderSetup.Result selected;
            boolean launched;
            try (ShaderSetup.Handle retained = owner) {
                selected = cold ? retained.prepare(progress,RuntimeWork.NEVER_CANCELLED)
                        : retained.selectPrepared(progress,RuntimeWork.NEVER_CANCELLED);
                launched = !retained.diagnosticLogs().isEmpty();
                if (launched != cold || !expectedImport.equals(selected.importGeneration))
                    throw new IllegalStateException("Shader owner or import selection differs");
                ShaderSetup.requireCurrent(context,root,wine,tools,selected,progress,RuntimeWork.NEVER_CANCELLED);
            }
            if (owner.processAlive() || owner.state() != ShaderSetup.State.CLOSED)
                throw new IllegalStateException("Owned shader process did not close");
            long modules;
            try (var paths=Files.walk(selected.shaders)) {
                modules=paths.filter(path->path.getFileName().toString().endsWith(".spv")).count();
            }
            if (selected.outputFiles != 4742 || modules != 1580 || selected.outputBytes <= 0)
                throw new IllegalStateException("Unexpected stock output inventory");
            JSONObject result = new JSONObject().put("mode",cold ? "cold" : "warm")
                    .put("generation",selected.generation).put("importGeneration",selected.importGeneration)
                    .put("files",selected.outputFiles).put("bytes",selected.outputBytes).put("modules",modules)
                    .put("wineGeneration",installedWine.generation).put("wineCopiedBytes",installedWine.copiedBytes)
                    .put("toolsGeneration",installedTools.generation).put("toolsCopiedBytes",installedTools.copiedBytes)
                    .put("ownedTranslatorLaunched",launched).put("ownerClosed",true)
                    .put("sessionReceiptAdmitted",true).put("elapsedMs",(System.nanoTime()-started)/1_000_000);
            System.out.println("ANDROID_SHADER_RESULT " + result);
        }
    }
}
