package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.diagnostics.SupportLogSelection;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;

/** Disposable signed-update realm only. SQL output is real. The client and
 * worldserver tails stand in for a session whose game assets are unavailable. */
final class PostStopExportFixture {
    static void prepare(Context ctx, Map<String,Path> database) throws IOException {
        Path root=ctx.getFilesDir().getCanonicalFile().toPath();
        Map<String,Path> selection=new LinkedHashMap<>();
        for(String stream : new String[]{"stdout","stderr"}) {
            Path log=database.get(stream);
            if(log==null || !Files.isRegularFile(log))throw new IOException("Missing stopped SQL wrapper stream");
            selection.put("game.database."+stream+".log",log);
        }
        String slot="feed000000000024", operation=slot+slot;
        Path client=root.resolve("s/"+slot+"/client/logs/stdout.log");
        Path world=root.resolve("db/"+slot+"/server-sessions/"+operation+"/worldserver.log");
        Files.createDirectories(client.getParent());
        Files.createDirectories(world.getParent());
        Files.write(client,("old client marker\n"+"pwd=x\n".repeat(11000)+"fixture client logout tail\n")
            .getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        Files.write(world,"password=fixture-private-value\nfixture world stop tail\n".getBytes(StandardCharsets.UTF_8),
            StandardOpenOption.CREATE_NEW);
        Path launcher=root.resolve("state/logs/launcher.log");
        Files.createDirectories(launcher.getParent());
        Files.write(launcher,"fixture cleanup check: observed SQL stop\n".getBytes(StandardCharsets.UTF_8),
            StandardOpenOption.CREATE,StandardOpenOption.APPEND);
        selection.put("game.presentation.client.stdout.log",client);
        selection.put("game.server.worldserver.log",world);
        if(!ctx.getSharedPreferences("session",Context.MODE_PRIVATE).edit().putString("ownedSupportLogs",
            SupportLogSelection.encodePreference(root,selection)).commit())throw new IOException("Could not persist export fixture");
        if(!ctx.getSharedPreferences("game-display",Context.MODE_PRIVATE).edit().putInt("lookPercent",150).commit())
            throw new IOException("Could not persist test setting");
    }
}
