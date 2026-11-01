package io.github.russianranger.esteria.runtime;

import android.content.Context;
import java.io.IOException;
import java.nio.file.Path;
import java.util.Set;

/** Source-owned data preparation helpers. Installation executes no extractor. */
public final class ServerDataAssets {
    static final Set<String> HELPERS=Set.of("server_data_generation.py","server_data_preflight.py",
        "shader_generation.py","extractor_order.py","owned_process_group.py","world_io.py");
    private ServerDataAssets(){ }
    public static String install(Context context,Path work)throws IOException {
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        if(work==null||!work.startsWith(root)||work.equals(root)||!work.toRealPath().equals(work))
            throw new IOException("Data preparation requires canonical private work storage");
        return GuestHelperAssets.install(context,"server-data",GuestHelperAssets.directory(work,"data-helpers"),HELPERS);
    }
}
