package io.github.russianranger.esteria.runtime;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Synthetic receipt/path guards only. No shader compiler or guest is executed. */
@RunWith(AndroidJUnit4.class)
public final class ShaderSetupReceiptTest {
    interface Action{void run()throws Exception;}
    static void refuses(Action action)throws Exception {try{action.run();}catch(IOException expected){return;}fail("Changed shader receipt accepted");}
    @Test public void packagedStockHelpersReuseAndPreserveChangedBytes()throws Exception {
        android.content.Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        Path helpers=StockClientSetup.installHelpers(context,root);
        java.util.Set<String> expected=java.util.Set.of("stock_content_inspection.py","stock_shader_generation.py",
            "shader_generation.py","extractor_order.py","server_data_preflight.py","world_io.py","stock_shader_translate.py");
        try(var files=Files.list(helpers)) {
            assertEquals(expected,files.map(path->path.getFileName().toString()).collect(java.util.stream.Collectors.toSet()));
        }
        assertEquals(helpers,StockClientSetup.installHelpers(context,root));
        Path coordinator=helpers.resolve("stock_shader_generation.py");
        byte[] original=Files.readAllBytes(coordinator),changed="changed-helper-preserved".getBytes(StandardCharsets.US_ASCII);
        try {
            Files.write(coordinator,changed);
            refuses(()->StockClientSetup.installHelpers(context,root));
            assertArrayEquals(changed,Files.readAllBytes(coordinator));
        }finally {Files.write(coordinator,original);}
        assertEquals(helpers,StockClientSetup.installHelpers(context,root));
    }
    @Test public void exactReceiptAndCurrentInputRequired()throws Exception {
        // Preserve the named component boundary while using independent Python
        // receipts and matching-Python-hash negative variants.
        new PythonReceiptBindingTest().pythonShaderGenerationAcceptedAndMutationsRejected();
    }
}
