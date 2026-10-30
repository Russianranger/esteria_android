package io.github.russianranger.esteria.core.runtime.process;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/** Fixed existing C component-probe contract. Parsing a receipt is not authority
 * to launch a client, reuse a result or claim complete Android/game readiness. */
public final class TurnipProbeContract {
    public static final long TIMEOUT_MILLIS=5000;
    public static final int MAX_RECEIPT_BYTES=4096;
    public static final String RECEIPT="probe.json";
    public static final String MOUNT="/esteria-turnip";
    private static final Set<String> FIELDS=Set.of("formatVersion","scope","icdLoaded","noKgslHostVerified",
        "turnip740ShaderReadbackQualified","directIcdNoDevicesVerified","loaderEnumerationResult",
        "pixelsVerified","vendorId","deviceId","deviceName","x11PresentationQualified","androidQualified","gameplayQualified");
    private TurnipProbeContract(){ }
    public static List<String> arguments(){return List.of(MOUNT+"/bin/esteria-turnip-probe",
        MOUNT+"/lib/libvulkan_freedreno.so","/work/"+RECEIPT,"--gpu-readback");}
    public static Map<String,String> driverEnvironment(){return Map.of("VK_DRIVER_FILES",MOUNT+"/etc/turnip-icd.json",
        "VK_ICD_FILENAMES",MOUNT+"/etc/turnip-icd.json","MESA_VK_WSI_DEBUG","sw",
        "VK_LAYER_PATH",MOUNT+"/no-layers","VK_IMPLICIT_LAYER_PATH",MOUNT+"/no-layers","VK_LOADER_LAYERS_DISABLE","~all~");}
    /** All values are source-owned; no user environment or alternate ICD enters. */
    public static Map<String,String> environment(Map<String,String> selectedDriver)throws IOException {
        require(driverEnvironment().equals(selectedDriver),"Turnip probe driver selection differs");
        Map<String,String> result=new TreeMap<>(selectedDriver);
        result.put("MESA_SHADER_CACHE_DISABLE","true");
        for(String name:List.of("XDG_CONFIG_HOME","XDG_CONFIG_DIRS","XDG_DATA_HOME","XDG_DATA_DIRS"))result.put(name,"/work/empty");
        return Map.copyOf(result);
    }
    public static final class Receipt {
        public final long deviceId;
        public final String deviceName;
        private Receipt(long deviceId,String deviceName){this.deviceId=deviceId;this.deviceName=deviceName;}
    }
    /** Exact output of the packaged --gpu-readback C path, never no-GPU CI. */
    public static Receipt validate(Map<String,?> value)throws IOException {
        require(value!=null&&value.keySet().equals(FIELDS),"Turnip component receipt fields differ");
        require(integer(value,"formatVersion")==2&&"linux-arm64-turnip-kgsl-component-probe".equals(value.get("scope")),
            "Turnip component receipt scope differs");
        for(String name:List.of("icdLoaded","turnip740ShaderReadbackQualified"))require(Boolean.TRUE.equals(value.get(name)),"Turnip component did not verify "+name);
        for(String name:List.of("noKgslHostVerified","directIcdNoDevicesVerified","x11PresentationQualified","androidQualified","gameplayQualified"))
            require(Boolean.FALSE.equals(value.get(name)),"Turnip component receipt overclaims or selects no-GPU mode");
        long device=integer(value,"deviceId");Object name=value.get("deviceName");
        require(integer(value,"loaderEnumerationResult")==0&&integer(value,"pixelsVerified")==4096&&
            integer(value,"vendorId")==0x5143&&device>0&&device<=0xffffffffL&&name instanceof String&&
            ((String)name).length()<=255&&((String)name).contains("740"),"Actual Turnip740 pixel readback required");
        String text=(String)name;
        for(int index=0;index<text.length();index++)require(text.charAt(index)>=32&&text.charAt(index)<=126,"Unexpected Turnip device name encoding");
        return new Receipt(device,text);
    }
    private static long integer(Map<String,?> value,String key)throws IOException {
        Object number=value.get(key);require(number instanceof Integer||number instanceof Long,"Exact Turnip receipt integer required");return ((Number)number).longValue();
    }
    private static void require(boolean ok,String reason)throws IOException {if(!ok)throw new IOException(reason);}
}
