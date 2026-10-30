package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/** Parsed trusted package pin. The Android adapter reads the shipped JSON lock. */
public final class RuntimePackagePlan {
    public static final class Limits {
        public final int maxEntries, maxPathBytes;
        public final long maxMemberBytes, maxFileBytes, maxMetadataBytes;
        public Limits(int maxEntries,long maxMemberBytes,long maxFileBytes,int maxPathBytes,long maxMetadataBytes) {
            if(maxEntries<1||maxEntries>100000||maxMemberBytes<1||maxMemberBytes>(1L<<30)||maxFileBytes<maxMemberBytes||maxFileBytes>(8L<<30)||maxPathBytes<1||maxPathBytes>4096||maxMetadataBytes<1024||maxMetadataBytes>(32L<<20)) throw new IllegalArgumentException("Invalid runtime limits");
            this.maxEntries=maxEntries;this.maxMemberBytes=maxMemberBytes;this.maxFileBytes=maxFileBytes;this.maxPathBytes=maxPathBytes;this.maxMetadataBytes=maxMetadataBytes;
        }
    }
    public static final class RequiredFile {
        public final long bytes;
        public final String sha256;
        public final int elfMachine, peMachine;
        public RequiredFile(long bytes,String sha256,int elfMachine,int peMachine) {
            if(bytes<0||bytes>(1L<<30)||sha256==null||!sha256.matches("[0-9a-f]{64}")||elfMachine<0||elfMachine>65535||peMachine<0||peMachine>65535||(elfMachine!=0&&peMachine!=0)) throw new IllegalArgumentException("Invalid runtime component pin");
            this.bytes=bytes;this.sha256=sha256;this.elfMachine=elfMachine;this.peMachine=peMachine;
        }
    }
    public final String packageId,sourcePinSha256,archiveName,archiveSha256,generation;
    public final long archiveBytes,expectedEntries,expectedFileBytes;
    public final Limits limits;
    public final Map<String,RequiredFile> required;
    public RuntimePackagePlan(String packageId,String sourcePinSha256,String archiveName,long archiveBytes,String archiveSha256,long expectedEntries,long expectedFileBytes,Limits limits,Map<String,RequiredFile> required) throws IOException {
        RuntimeFiles.require(packageId!=null&&packageId.matches("[a-z0-9][a-z0-9-]{0,63}"),"Invalid runtime package identity");
        RuntimeFiles.hashPin(sourcePinSha256);RuntimeFiles.hashPin(archiveSha256);
        RuntimeFiles.require(archiveName!=null&&archiveName.matches("[A-Za-z0-9._-]{1,128}")&&!archiveName.equals(".")&&!archiveName.equals(".."),"Invalid archive filename");
        RuntimeFiles.require(archiveBytes>0&&archiveBytes<=(8L<<30)&&expectedEntries>0&&expectedEntries<=limits.maxEntries&&expectedFileBytes>=0&&expectedFileBytes<=limits.maxFileBytes,"Invalid runtime inventory pin");
        RuntimeFiles.require(required!=null&&!required.isEmpty()&&required.size()<=512,"Runtime component pins are required");
        TreeMap<String,RequiredFile> safe=new TreeMap<>();
        for(Map.Entry<String,RequiredFile> entry:required.entrySet()) {
            String path=RuntimeFiles.memberPath(entry.getKey(),limits.maxPathBytes);
            RuntimeFiles.require(path.equals(entry.getKey())&&entry.getValue()!=null&&entry.getValue().bytes<=limits.maxMemberBytes,"Invalid runtime required file");
            safe.put(path,entry.getValue());
        }
        this.packageId=packageId;this.sourcePinSha256=sourcePinSha256;this.archiveName=archiveName;this.archiveBytes=archiveBytes;this.archiveSha256=archiveSha256;this.expectedEntries=expectedEntries;this.expectedFileBytes=expectedFileBytes;this.limits=limits;this.required=Collections.unmodifiableMap(safe);
        StringBuilder identity=new StringBuilder("esteria-runtime-v1\n").append(packageId).append('\n').append(sourcePinSha256).append('\n').append(archiveSha256).append('\n').append(archiveBytes).append('\n').append(expectedEntries).append('\n').append(expectedFileBytes).append('\n');
        for(Map.Entry<String,RequiredFile> entry:safe.entrySet()){RequiredFile f=entry.getValue();identity.append(entry.getKey()).append('\t').append(f.bytes).append('\t').append(f.sha256).append('\t').append(f.elfMachine).append('\t').append(f.peMachine).append('\n');}
        generation=RuntimeFiles.hashText(identity.toString());
    }
}
