package io.github.russianranger.esteria.core.runtime.process;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** Explicit PRoot argv; callers provide verified payloads and private directories.
 * PRoot is a compatibility layer, not a security or network sandbox.
 */
public final class ProotLaunch {
    private ProotLaunch() { }
    public static OwnedProcess.Specification create(Path tracer,Path loader,Path rootfs,Path work,
            Path temporary,Path logs,List<String> guestCommand,Map<String,String> guestEnvironment) throws IOException {
        for (Path path : Arrays.asList(rootfs,work,temporary,logs)) directory(path);
        for (Path path : Arrays.asList(tracer,loader)) {
            if (!path.isAbsolute() || Files.isSymbolicLink(path) || !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !Files.isExecutable(path))
                throw new IOException("Missing installed PRoot executable");
        }
        if (guestCommand.isEmpty() || !guestCommand.get(0).startsWith("/")) throw new IOException("Absolute guest executable required");
        if (rootfs.startsWith(work) || work.startsWith(rootfs) || temporary.startsWith(rootfs) || rootfs.startsWith(temporary) ||
                logs.startsWith(rootfs) || rootfs.startsWith(logs))
            throw new IOException("Mutable process state must be outside the runtime generation");
        List<String> args=new ArrayList<>(Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),
            "-b","/dev","-b","/proc","-b",work+":/work","-b",temporary+":/tmp","-w","/work","/usr/bin/env","-i"));
        Map<String,String> guest=new TreeMap<>();
        guest.put("PATH","/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin");
        guest.put("HOME","/work/home"); guest.put("USER","root"); guest.put("LANG","C.UTF-8"); guest.put("TMPDIR","/tmp");
        for (Map.Entry<String,String> item : guestEnvironment.entrySet()) {
            if (!item.getKey().matches("[A-Za-z_][A-Za-z0-9_]*") || item.getKey().startsWith("PROOT_"))
                throw new IOException("Invalid guest environment key");
            guest.put(item.getKey(),item.getValue());
        }
        for (Map.Entry<String,String> item : guest.entrySet()) args.add(item.getKey()+"="+item.getValue());
        args.addAll(guestCommand);
        Map<String,String> host=new TreeMap<>();
        host.put("PROOT_LOADER",loader.toString()); host.put("PROOT_TMP_DIR",temporary.toString());
        host.put("PROOT_NO_SECCOMP","1"); host.put("PATH","/system/bin");
        return new OwnedProcess.Specification(tracer,args,host,
            work,logs.resolve("stdout.log"),logs.resolve("stderr.log"));
    }
    private static void directory(Path path) throws IOException {
        if (!path.isAbsolute() || !path.normalize().equals(path) || path.toString().indexOf(':')>=0 ||
                Files.isSymbolicLink(path) || !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !path.toRealPath().equals(path))
            throw new IOException("Process directories must be existing canonical directories");
    }
}
