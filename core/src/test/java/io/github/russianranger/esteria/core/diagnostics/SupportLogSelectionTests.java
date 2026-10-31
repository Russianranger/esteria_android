package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** Real temporary filesystem metadata fixtures. No log file contents are read
 * by the selection utility and no Android/guest execution is implied. */
public final class SupportLogSelectionTests {
    private static final String OP="a".repeat(32),SLOT="b".repeat(16);
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private interface Action {void run()throws IOException;}
    private static void refused(Action action)throws IOException {try{action.run();throw new AssertionError("Invalid diagnostic selection accepted");}catch(IOException expected){ }}
    private static Map<String,Path> roles(Path root) {
        Map<String,Path> result=new LinkedHashMap<>();
        for(String stream:List.of("stdout","stderr")) {
            result.put("game.database."+stream+".log",root.resolve("state/database-service-operations/"+OP+"/logs/"+stream+".log"));
            result.put("game.server.helper."+stream+".log",root.resolve("state/server-session-runtime-operations/"+OP+"/logs/"+stream+".log"));
            for(String component:List.of("xserver","frame","input","client"))result.put("game.presentation."+component+"."+stream+".log",root.resolve("s/"+SLOT+"/"+component+"/logs/"+stream+".log"));
            for(String setup:List.of("data","shader","stock","installation","turnip")) {
                String directory=setup.equals("data")?"server-data-operations":setup.equals("shader")?"shader-operations":setup.equals("stock")?"stock-client-operations":setup.equals("turnip")?"turnip-probe-operations":"server-installation-processes";
                result.put("setup."+setup+"."+stream+".log",root.resolve("state/"+directory+"/"+OP+"/logs/"+stream+".log"));
            }
        }
        for(String server:List.of("authserver","worldserver"))result.put("game.server."+server+".log",root.resolve("db/"+SLOT+"/server-sessions/"+OP+"/"+server+".log"));
        return result;
    }
    private static void roundTripAndRotation()throws Exception {
        Path root=Files.createTempDirectory("esteria-log-selection-").toRealPath();
        try {
            Map<String,Path> logs=roles(root);check(logs.size()==24,"Only24 actual fixed roles are defined");
            // Every future log is initially absent: selection must not invent,
            // create or demand one before the source helper starts.
            String encoded=SupportLogSelection.encode(root,logs);check(SupportLogSelection.decode(root,encoded).equals(logs),"Missing future paths round-trip");
            try(var children=Files.list(root)){check(children.findAny().isEmpty(),"Metadata selection creates no files/directories");}
            Map<String,Path> reversed=new LinkedHashMap<>();List<String> names=new ArrayList<>(logs.keySet());java.util.Collections.reverse(names);names.forEach(name->reversed.put(name,logs.get(name)));
            check(encoded.equals(SupportLogSelection.encode(root,reversed)),"Encoding is deterministic across input order");
            Path target=logs.get("game.server.worldserver.log");Files.createDirectories(target.getParent());Files.writeString(target,"TEST_ONLY_LOG_CONTENT");
            var modified=Files.getLastModifiedTime(target);String saved=SupportLogSelection.encode(root,logs);Files.move(target,target.resolveSibling("rotated.log"));
            check(SupportLogSelection.decode(root,saved).equals(logs),"Rotated/missing log paths survive decode without replacement");
            check(Files.getLastModifiedTime(target.resolveSibling("rotated.log")).equals(modified),"Selection leaves existing log metadata unchanged");
            Map<String,Path> decoded=SupportLogSelection.decode(root,saved);try{decoded.clear();throw new AssertionError("Decoded map is mutable");}catch(UnsupportedOperationException expected){ }
            check(SupportLogSelection.decode(root,"").isEmpty()&&SupportLogSelection.decode(root,SupportLogSelection.encode(root,Map.of())).isEmpty(),"Absent and empty saved selections are explicit");
        }finally{remove(root);}
    }
    private static void badMetadata()throws Exception {
        Path root=Files.createTempDirectory("esteria-log-selection-bad-").toRealPath(),foreign=Files.createTempDirectory("esteria-log-selection-foreign-").toRealPath();
        try {
            Map<String,Path> logs=roles(root);String key="game.database.stdout.log",good=SupportLogSelection.encode(root,Map.of(key,logs.get(key)));
            for(Path bad:List.of(foreign.resolve("stdout.log"),root.resolve("state/../state/database-service-operations/"+OP+"/logs/stdout.log"),Path.of("relative/stdout.log")))refused(()->SupportLogSelection.encode(root,Map.of(key,bad)));
            for(String wrong:List.of("user.stdout.log","10.game.database.stdout.log","game.database.stdout.log\tsecret","game.database.stdout.log\nsecret","game.database.password.log","launcher.log"))refused(()->SupportLogSelection.encode(root,Map.of(wrong,logs.get(key))));
            String line=good.substring(good.indexOf('\n')+1);
            for(String changed:List.of(good.replace("v1","v2"),good.substring(0,good.length()-1),good+line,good+"\n",good.replace("\tstate/","\t/state/"),good.replace("logs/stdout.log","logs/../stdout.log"),good.replace("logs/stdout.log","logs\\stdout.log"),good.replace("stdout.log\n","stdout.log\r\n"),"x".repeat(SupportLogSelection.MAX_ENCODED_BYTES+1)))refused(()->SupportLogSelection.decode(root,changed));
            Map<String,Path> tooMany=new TreeMap<>();for(int index=0;index<33;index++)tooMany.put("role"+index,logs.get(key));refused(()->SupportLogSelection.encode(root,tooMany));
            refused(()->SupportLogSelection.decode(root,good.replace(OP,"a".repeat(1025))));
            refused(()->SupportLogSelection.encode(root,Map.of(key,logs.get("game.database.stderr.log"))));
            refused(()->SupportLogSelection.encode(root,Map.of("setup.turnip.stdout.log",root.resolve("state/turnip-probe-work/"+OP+"/probe.json"))));
            refused(()->SupportLogSelection.encode(root,Map.of("setup.turnip.stdout.log",logs.get("setup.shader.stdout.log"))));
            refused(()->SupportLogSelection.encode(root.resolve(".."),Map.of()));
        }finally{remove(root);remove(foreign);}
    }
    private static void privatePathsAndSymlinks()throws Exception {
        Path root=Files.createTempDirectory("esteria-log-selection-private-").toRealPath(),foreign=Files.createTempDirectory("esteria-log-selection-target-").toRealPath();
        try {
            String key="game.database.stdout.log";Map<String,Path> logs=roles(root);Path target=logs.get(key);
            for(String forbidden:List.of("accounts","config","WTF","client-state","home","prefix","game","runtimes","handoffs")) {
                Path path=root.resolve("state/"+forbidden+"/stdout.log");refused(()->SupportLogSelection.encode(root,Map.of(key,path)));
            }
            for(String forbidden:List.of("engine-private.log","local-player.json","receipt.json","esteria-local-login.bin","Xauthority"))refused(()->SupportLogSelection.encode(root,Map.of(key,target.resolveSibling(forbidden))));
            refused(()->SupportLogSelection.encode(root,Map.of(key,root.resolve("server-data-work/logs/stdout.log"))));
            Files.createDirectories(target.getParent());Files.writeString(foreign.resolve("credential"),"TEST_ONLY_PRIVATE_SENTINEL");
            String saved=SupportLogSelection.encode(root,Map.of(key,target));Files.createSymbolicLink(target,foreign.resolve("credential"));
            refused(()->SupportLogSelection.encode(root,Map.of(key,target)));refused(()->SupportLogSelection.decode(root,saved));Files.delete(target);
            Path parent=target.getParent();Files.delete(parent);Files.createSymbolicLink(parent,foreign);
            refused(()->SupportLogSelection.decode(root,saved));Files.delete(parent);Files.writeString(parent,"TEST_ONLY_NON_DIRECTORY");refused(()->SupportLogSelection.decode(root,saved));Files.delete(parent);
            Files.createDirectories(parent);Files.createDirectory(target);refused(()->SupportLogSelection.decode(root,saved));Files.delete(target);
            Path alias=foreign.resolve("root-alias");Files.createSymbolicLink(alias,root);refused(()->SupportLogSelection.decode(alias,saved));
            check(Files.readString(foreign.resolve("credential")).equals("TEST_ONLY_PRIVATE_SENTINEL"),"Rejected symlinks never read/modify/delete private content");
        }finally{remove(root);remove(foreign);}
    }
    private static void remove(Path root)throws IOException {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    public static void main(String[] arguments)throws Exception {
        roundTripAndRotation();badMetadata();privatePathsAndSymlinks();
        System.out.println("Support log selection passed3 actual filesystem metadata groups:24 fixed roles, missing/rotated roundtrip, bounds/private/foreign/traversal/symlink refusal; no log bytes read by selector");
    }
}
