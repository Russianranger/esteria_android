import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.TreeMap;

/** Host filesystem reference over exact provider pins; executes no guest program. */
public final class ServerArchiveInstallReference {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("manifest archive private-store required");
        Path manifest=Path.of(args[0]), archive=Path.of(args[1]), store=Path.of(args[2]);
        if (Files.size(manifest)>4L*1024*1024) throw new IllegalArgumentException("manifest bound");
        String[] header; Map<String,RuntimePackagePlan.RequiredFile> required=new TreeMap<>();
        try (BufferedReader reader=Files.newBufferedReader(manifest,StandardCharsets.UTF_8)) {
            header=reader.readLine().split("\t",-1);
            if(header.length!=13 || !header[0].equals("P"))throw new IllegalArgumentException("manifest header");
            for(String line;(line=reader.readLine())!=null;) {
                String[] row=line.split("\t",-1);
                if(row.length!=6 || !row[0].equals("F") || required.size()>=512 || required.containsKey(row[1]))
                    throw new IllegalArgumentException("manifest row");
                required.put(row[1],new RuntimePackagePlan.RequiredFile(Long.parseLong(row[2]),row[3],Integer.parseInt(row[4]),Integer.parseInt(row[5])));
            }
        }
        RuntimePackagePlan.Limits limits=new RuntimePackagePlan.Limits(Integer.parseInt(header[8]),Long.parseLong(header[9]),
            Long.parseLong(header[10]),Integer.parseInt(header[11]),Long.parseLong(header[12]));
        RuntimePackagePlan plan=new RuntimePackagePlan(header[1],header[2],header[3],Long.parseLong(header[4]),header[5],
            Long.parseLong(header[6]),Long.parseLong(header[7]),limits,required);
        RuntimeInstaller installer=new RuntimeInstaller(store);
        RuntimeInstaller.Result first=installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller.Result cached=installer.install(store.resolve("missing-unused-archive"),plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        if(first.alreadyInstalled || !cached.alreadyInstalled || cached.copiedBytes!=0 || !first.rootfs.equals(cached.rootfs))
            throw new AssertionError("actual archive fresh install/cache reuse failed");
        System.out.println("{\"scope\":\"host-java-exact-server-archive-install-and-cached-reuse\",\"packageKey\":\""+plan.packageId+
            "\",\"generation\":\""+plan.generation+"\",\"entries\":"+plan.expectedEntries+",\"fileBytes\":"+plan.expectedFileBytes+
            ",\"firstCopiedBytes\":"+first.copiedBytes+",\"cachedCopiedBytes\":0,\"cachedArchiveRequired\":false,\"androidRuntimeQualified\":false,\"gameplayQualified\":false}");
    }
}
