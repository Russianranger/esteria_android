package android.content;

import android.content.res.AssetManager;
import java.io.File;

/** Qualification filesystem facade only; no Android execution is claimed. */
public final class Context {
    private final File files;
    private final AssetManager assets;
    public Context(File files,AssetManager assets){this.files=files;this.assets=assets;}
    public Context getApplicationContext(){return this;}
    public File getFilesDir(){return files;}
    public AssetManager getAssets(){return assets;}
}
