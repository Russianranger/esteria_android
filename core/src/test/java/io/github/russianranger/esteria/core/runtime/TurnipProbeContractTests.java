package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.core.runtime.process.TurnipProbeContract;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Contract fixtures only: never load Vulkan, invoke a driver or qualify a GPU. */
public final class TurnipProbeContractTests {
    interface Action {void run()throws Exception;}
    static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    static void refuse(Action action)throws Exception {try{action.run();throw new AssertionError("Unsafe probe contract accepted");}catch(IOException expected){ }}
    static Map<String,Object> receipt(){return new HashMap<>(Map.ofEntries(Map.entry("formatVersion",2),Map.entry("scope","linux-arm64-turnip-kgsl-component-probe"),
        Map.entry("icdLoaded",true),Map.entry("noKgslHostVerified",false),Map.entry("turnip740ShaderReadbackQualified",true),
        Map.entry("directIcdNoDevicesVerified",false),Map.entry("loaderEnumerationResult",0),Map.entry("pixelsVerified",4096),
        Map.entry("vendorId",0x5143),Map.entry("deviceId",740),Map.entry("deviceName","TEST_ONLY Turnip Adreno740 contract fixture"),
        Map.entry("x11PresentationQualified",false),Map.entry("androidQualified",false),Map.entry("gameplayQualified",false)));}
    public static void main(String[] args)throws Exception {
        var original=receipt();var parsed=TurnipProbeContract.validate(original);check(parsed.deviceId==740,"Device identity not retained");
        for(String field:original.keySet()) {
            var changed=receipt();changed.remove(field);refuse(()->TurnipProbeContract.validate(changed));
        }
        for(String field:List.of("formatVersion","loaderEnumerationResult","pixelsVerified","vendorId","deviceId")) {
            var changed=receipt();changed.put(field,Double.valueOf(((Number)original.get(field)).doubleValue()));refuse(()->TurnipProbeContract.validate(changed));
        }
        for(String field:List.of("icdLoaded","noKgslHostVerified","turnip740ShaderReadbackQualified","directIcdNoDevicesVerified","x11PresentationQualified","androidQualified","gameplayQualified")) {
            var changed=receipt();changed.put(field,!((Boolean)original.get(field)));refuse(()->TurnipProbeContract.validate(changed));
        }
        for(var substitution:Map.<String,Object>of("scope","forged","pixelsVerified",4095,"vendorId",0x10005,"deviceId",0,"deviceName","llvmpipe").entrySet()) {
            var changed=receipt();changed.put(substitution.getKey(),substitution.getValue());refuse(()->TurnipProbeContract.validate(changed));
        }
        var extra=receipt();extra.put("selfQualified",true);refuse(()->TurnipProbeContract.validate(extra));
        var control=receipt();control.put("deviceName","Adreno740\nforged status");refuse(()->TurnipProbeContract.validate(control));
        var noGpu=receipt();noGpu.put("noKgslHostVerified",true);noGpu.put("turnip740ShaderReadbackQualified",false);noGpu.put("pixelsVerified",0);refuse(()->TurnipProbeContract.validate(noGpu));
        check(TurnipProbeContract.arguments().equals(List.of("/esteria-turnip/bin/esteria-turnip-probe","/esteria-turnip/lib/libvulkan_freedreno.so","/work/probe.json","--gpu-readback")),"Probe command drift");
        check(TurnipProbeContract.TIMEOUT_MILLIS==5000&&TurnipProbeContract.MAX_RECEIPT_BYTES==4096,"Probe limits drift");
        var environment=TurnipProbeContract.environment(TurnipProbeContract.driverEnvironment());
        check(environment.get("VK_DRIVER_FILES").equals("/esteria-turnip/etc/turnip-icd.json")&&!environment.containsKey("DISPLAY")&&!environment.containsKey("LD_PRELOAD"),"Probe inherited presentation or loader overrides");
        var foreign=new HashMap<>(TurnipProbeContract.driverEnvironment());foreign.put("VK_DRIVER_FILES","/user/icd.json");refuse(()->TurnipProbeContract.environment(foreign));
        var injected=new HashMap<>(TurnipProbeContract.driverEnvironment());injected.put("LD_PRELOAD","/user/library.so");refuse(()->TurnipProbeContract.environment(injected));
        Path root=Files.createTempDirectory("turnip-probe-argv-").toRealPath();
        try {
            Path tracer=Files.writeString(root.resolve("tracer"),"fixture"),loader=Files.writeString(root.resolve("loader"),"fixture");tracer.toFile().setExecutable(true);loader.toFile().setExecutable(true);
            Path runtime=Files.createDirectory(root.resolve("runtime")),work=Files.createDirectory(root.resolve("work")),tmp=Files.createDirectory(root.resolve("tmp")),logs=Files.createDirectory(root.resolve("logs")),driver=Files.createDirectory(root.resolve("driver"));
            var spec=ProotLaunch.create(tracer,loader,runtime,work,tmp,logs,TurnipProbeContract.arguments(),environment,List.of(new ProotLaunch.Mount(driver,TurnipProbeContract.MOUNT)));
            check(spec.arguments.contains(driver+":/esteria-turnip!")&&spec.arguments.contains("VK_DRIVER_FILES=/esteria-turnip/etc/turnip-icd.json"),"Actual PRoot command lost driver binding");
            check(spec.arguments.contains("/usr/bin/env")&&spec.arguments.contains("-i")&&!spec.environment.containsKey("VK_DRIVER_FILES"),"Guest-only sanitized environment contract differs");
            check(!spec.arguments.contains("/esteria-client")&&!spec.arguments.contains("/esteria-data"),"Probe unexpectedly mounts game data");
        }finally{try(var files=Files.walk(root)){for(Path p:files.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(p);}}
        System.out.println("Turnip component contract: fixed sanitized PRoot argv, exclusive ICD, strict GPU-only receipt and false broad-claim guards passed; no Vulkan/Android/GPU execution");
    }
}
