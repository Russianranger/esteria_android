package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/** Plain decoded-descriptor guards on the host, with the actual production
 * validator. Fixture identities attest no archive, ELF, source or SQL execution.
 * Android's JSON parser and AssetManager are not replaced with host stubs. */
public final class ServerProgramsProfileTests {
    private static final String STOCK="a".repeat(64);
    private static final Set<String> PROGRAMS=Set.of("authserver","worldserver","dbimport");
    private static final RuntimePackagePlan.RequiredFile ORIGINAL=new RuntimePackagePlan.RequiredFile(100,"b".repeat(64),0,0);
    @FunctionalInterface private interface Checked {void run()throws IOException;}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static void refuses(Checked operation)throws IOException {try{operation.run();throw new AssertionError("Changed optional descriptor accepted");}catch(IOException expected){ }}
    private static Map<String,Object> pin(long bytes,char hash){return new TreeMap<>(Map.of("bytes",bytes,"sha256",String.valueOf(hash).repeat(64)));}
    private static Map<String,Object> named(String file,long bytes,char hash){Map<String,Object> result=pin(bytes,hash);result.put("file",file);return result;}
    @SuppressWarnings("unchecked") private static Map<String,Object> object(Map<String,Object> parent,String key){return (Map<String,Object>)parent.get(key);}
    private static Map<String,Object> optional(){
        Map<String,Object> helper=new TreeMap<>();helper.put("name","playerbots-schema");helper.put("role","playerbots-schema-initializer");
        helper.put("guestPath","/esteria-server-programs/helpers/playerbots-schema");helper.put("executable",pin(25_188_512,'c'));
        helper.put("buildReceipt",pin(32_008,'d'));helper.put("nativeSqlReceipt",pin(37_703,'e'));helper.put("sourceReceipt",pin(1_320_302,'f'));
        helper.put("sourceQualification",new TreeMap<>(Map.of("archive",named("playerbots-helper-complete-sources.tar.gz",108_559_554,'1'),
            "receipt",named("playerbots-source-receipt.json",1_320_302,'f'),"nativeObservationReceipt",pin(42_641,'2'))));
        for(String flag:Set.of("sourceCompanionRequired","sourceCompanionVerified","nativeSqlQualified","originalThreeProgramsUnchanged"))helper.put(flag,true);
        for(String flag:Set.of("androidRuntimeQualified","worldserverQualified","playerbotsAiQualified","gameplayQualified"))helper.put(flag,false);
        return new TreeMap<>(Map.of("profile","playerbots-schema-helper","helperNames",List.of("playerbots-schema"),
            "originalStockInputLockSha256",STOCK,"originalProgramsArchive",named("server-programs-runtime-arm64.tar.gz",100,'b'),
            "playerbotsHelper",helper,"helperNoticeFiles",new TreeMap<>(Map.of(ServerProgramsSetup.HELPER_NOTICE,pin(35_149,'3')))));
    }
    private static Map<String,RuntimePackagePlan.RequiredFile> stock(){
        Map<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
        for(String name:PROGRAMS){files.put("bin/"+name,new RuntimePackagePlan.RequiredFile(64,"4".repeat(64),183,0));files.put("etc/"+name+".conf.dist",new RuntimePackagePlan.RequiredFile(64,"5".repeat(64),0,0));}
        for(int i=0;i<120;i++)files.put("notices/TEST_ONLY_"+i,new RuntimePackagePlan.RequiredFile(64,"6".repeat(64),0,0));return files;
    }
    private static Map<String,RuntimePackagePlan.RequiredFile> helpers(Map<String,Object> value)throws IOException{return ServerProgramsSetup.helperFiles(value,STOCK,ORIGINAL);}
    private static void stockAndOptional()throws IOException {
        Map<String,RuntimePackagePlan.RequiredFile> stock=stock();check(stock.size()==126,"Fixture preserves126 original roles");
        check(helpers(Map.of()).isEmpty(),"No profile retains stock selection");ServerProgramsSetup.requireFileSelection(stock,PROGRAMS,PROGRAMS,Map.of());
        Map<String,RuntimePackagePlan.RequiredFile> additions=helpers(optional());check(additions.size()==5,"Only five declared additions");
        check(additions.get(ServerProgramsSetup.HELPER).elfMachine==183,"Fixed helper is the sole new ELF role");
        check(additions.get(ServerProgramsSetup.HELPER_SOURCE).bytes==1_320_302,"Large source receipt remains an opaque file pin");
        Map<String,RuntimePackagePlan.RequiredFile> complete=new TreeMap<>(stock);complete.putAll(additions);
        check(complete.size()==131&&complete.entrySet().containsAll(stock.entrySet()),"Optional fixture preserves original entries");
        ServerProgramsSetup.requireFileSelection(complete,PROGRAMS,PROGRAMS,additions);
    }
    private static void metadataRefusals()throws IOException {
        Map<String,Object> value=optional();value.put("profile","unmeasured");refuses(()->helpers(value));
        Map<String,Object> original=optional();original.put("originalStockInputLockSha256","0".repeat(64));refuses(()->helpers(original));
        Map<String,Object> archive=optional();object(archive,"originalProgramsArchive").put("sha256","0".repeat(64));refuses(()->helpers(archive));
        Map<String,Object> names=optional();names.put("helperNames",List.of("playerbots-schema","playerbots-schema"));refuses(()->helpers(names));
        for(String field:List.of("name","role","guestPath")){Map<String,Object> changed=optional();object(changed,"playerbotsHelper").put(field,"arbitrary");refuses(()->helpers(changed));}
        for(String flag:List.of("sourceCompanionRequired","sourceCompanionVerified","nativeSqlQualified","originalThreeProgramsUnchanged")){
            Map<String,Object> changed=optional();object(changed,"playerbotsHelper").put(flag,false);refuses(()->helpers(changed));
        }
        for(String flag:List.of("androidRuntimeQualified","worldserverQualified","playerbotsAiQualified","gameplayQualified")){
            Map<String,Object> changed=optional();object(changed,"playerbotsHelper").put(flag,true);refuses(()->helpers(changed));
        }
        Map<String,Object> stringFlag=optional();object(stringFlag,"playerbotsHelper").put("nativeSqlQualified","true");refuses(()->helpers(stringFlag));
        Map<String,Object> extra=optional();object(extra,"playerbotsHelper").put("worldExecuted",true);refuses(()->helpers(extra));
    }
    private static void sourceAndNoticeRefusals()throws IOException {
        Map<String,Object> receipt=optional();object(object(receipt,"playerbotsHelper"),"sourceReceipt").put("sha256","0".repeat(64));refuses(()->helpers(receipt));
        Map<String,Object> source=optional();object(object(object(source,"playerbotsHelper"),"sourceQualification"),"archive").put("file","other.tar.gz");refuses(()->helpers(source));
        Map<String,Object> notices=optional();object(notices,"helperNoticeFiles").put("helper-notices/extra",pin(1,'0'));refuses(()->helpers(notices));
        Map<String,Object> size=optional();object(object(size,"playerbotsHelper"),"sourceReceipt").put("bytes",1.5);refuses(()->helpers(size));
        Map<String,Object> absent=new TreeMap<>();absent.put("playerbotsHelper",object(optional(),"playerbotsHelper"));refuses(()->helpers(absent));
    }
    private static void fileRoleRefusals()throws IOException {
        Map<String,RuntimePackagePlan.RequiredFile> additions=helpers(optional()),complete=new TreeMap<>(stock());complete.putAll(additions);
        Map<String,RuntimePackagePlan.RequiredFile> missing=new TreeMap<>(complete);missing.remove(ServerProgramsSetup.HELPER_SOURCE);refuses(()->ServerProgramsSetup.requireFileSelection(missing,PROGRAMS,PROGRAMS,additions));
        Map<String,RuntimePackagePlan.RequiredFile> changed=new TreeMap<>(complete);changed.put(ServerProgramsSetup.HELPER_SOURCE,new RuntimePackagePlan.RequiredFile(1,"0".repeat(64),0,0));refuses(()->ServerProgramsSetup.requireFileSelection(changed,PROGRAMS,PROGRAMS,additions));
        Map<String,RuntimePackagePlan.RequiredFile> wrongMachine=new TreeMap<>(complete);wrongMachine.put(ServerProgramsSetup.HELPER,new RuntimePackagePlan.RequiredFile(25_188_512,"c".repeat(64),0,0));refuses(()->ServerProgramsSetup.requireFileSelection(wrongMachine,PROGRAMS,PROGRAMS,additions));
        Map<String,RuntimePackagePlan.RequiredFile> foreign=new TreeMap<>(complete);foreign.remove("notices/TEST_ONLY_0");foreign.put("helpers/other",new RuntimePackagePlan.RequiredFile(64,"0".repeat(64),183,0));refuses(()->ServerProgramsSetup.requireFileSelection(foreign,PROGRAMS,PROGRAMS,additions));
        Map<String,RuntimePackagePlan.RequiredFile> hidden=new TreeMap<>(complete);hidden.put(ServerProgramsSetup.HELPER_NATIVE,new RuntimePackagePlan.RequiredFile(37_703,"e".repeat(64),183,0));refuses(()->ServerProgramsSetup.requireFileSelection(hidden,PROGRAMS,PROGRAMS,additions));
        refuses(()->ServerProgramsSetup.requireFileSelection(complete,PROGRAMS,Set.of("authserver","worldserver","dbimport","other"),additions));
        refuses(()->ServerProgramsSetup.requireFileSelection(complete,PROGRAMS,PROGRAMS,Map.of()));
    }
    public static void main(String[] args)throws Exception {
        stockAndOptional();metadataRefusals();sourceAndNoticeRefusals();fileRoleRefusals();
        System.out.println("Server programs passed4 decoded-profile host guard groups; no JSON/asset/native/source/SQL/Android execution claim");
    }
}
