package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import java.nio.file.Path;
import org.json.JSONObject;

/** Run the shipping metadata consumer against the selected complete private import and genuine receipt. */
public final class StockWorldBinding {
    public static void main(String[] args) throws Exception {
        if (args.length != 8) throw new IllegalArgumentException("Expected the selected data owner and its pins");
        ServerDataRunPlan plan = new ServerDataRunPlan(Path.of(args[0]), Path.of(args[1]), Path.of(args[2]),
                args[3], args[4], "enUS", 1);
        ServerDataBinding bound = ServerDataBinding.inspect(plan, args[5]);
        bound.requireUnchanged();
        if (!bound.dataRecipe().equals(args[6]) || !bound.generation.equals(args[7]))
            throw new IllegalStateException("Selected Android recipe or data generation differs");
        System.out.println(new JSONObject().put("generation", bound.generation).put("installedReader", bound.installedDataReader())
                .put("outputRecipe", bound.dataRecipe()).put("toolSelectionSha256", plan.toolSelectionSha256)
                .put("importGeneration", plan.importGeneration).put("threads", plan.threads)
                .put("payloadBytes", bound.payloadBytes).put("effectiveLocale", bound.effectiveLocale));
    }
}
