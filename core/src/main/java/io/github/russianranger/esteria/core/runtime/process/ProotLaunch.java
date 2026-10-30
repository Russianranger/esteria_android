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
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/** Explicit PRoot argv; callers provide verified payloads and private directories.
 * PRoot is a compatibility layer, not a security or network sandbox.
 */
public final class ProotLaunch {
    private ProotLaunch() { }
    /** Immutable provider/data location by convention, not an enforced read-only mount.
     * PRoot cannot make same-UID application files into a security boundary.
     */
    public static final class Mount {
        public final Path source;
        public final String destination;
        public Mount(Path source, String destination) {
            if (source == null || destination == null || !Arrays.asList("/esteria-client", "/esteria-data",
                    "/esteria-content", "/esteria-server", "/esteria-server-programs", "/esteria-server-content", "/esteria-server-extractors", "/esteria-bridges", "/esteria-shaders", "/esteria-shader-tools", "/esteria-turnip").contains(destination))
                throw new IllegalArgumentException("Unsupported runtime provider mount");
            this.source = source; this.destination = destination;
        }
    }
    /** Mutable private IPC only; each process still has separate /tmp and logs. */
    public static final class PresentationBindings {
        public final Path endpoints, x11;
        public PresentationBindings(Path endpoints, Path x11) {
            if (endpoints == null || x11 == null) throw new IllegalArgumentException("Presentation IPC directories required");
            this.endpoints=endpoints; this.x11=x11;
        }
    }
    public static OwnedProcess.Specification create(Path tracer,Path loader,Path rootfs,Path work,
            Path temporary,Path logs,List<String> guestCommand,Map<String,String> guestEnvironment) throws IOException {
        return create(tracer,loader,rootfs,work,temporary,logs,guestCommand,guestEnvironment,Collections.emptyList());
    }
    public static OwnedProcess.Specification create(Path tracer,Path loader,Path rootfs,Path work,
            Path temporary,Path logs,List<String> guestCommand,Map<String,String> guestEnvironment,List<Mount> mounts) throws IOException {
        return create(tracer,loader,rootfs,work,temporary,logs,guestCommand,guestEnvironment,mounts,null);
    }
    public static OwnedProcess.Specification create(Path tracer,Path loader,Path rootfs,Path work,
            Path temporary,Path logs,List<String> guestCommand,Map<String,String> guestEnvironment,List<Mount> mounts,
            PresentationBindings presentation) throws IOException {
        for (Path path : Arrays.asList(rootfs,work,temporary,logs)) directory(path);
        for (Path path : Arrays.asList(tracer,loader)) {
            if (!path.isAbsolute() || Files.isSymbolicLink(path) || !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !Files.isExecutable(path))
                throw new IOException("Missing installed PRoot executable");
        }
        if (guestCommand.isEmpty() || !guestCommand.get(0).startsWith("/")) throw new IOException("Absolute guest executable required");
        List<Path> baseDirectories=Arrays.asList(rootfs,work,temporary,logs);
        for (int i=0;i<baseDirectories.size();i++) for (int j=i+1;j<baseDirectories.size();j++)
            if (overlap(baseDirectories.get(i),baseDirectories.get(j)))
                throw new IOException("Runtime, persistent work, temporary files and logs must be separate");
        List<String> args=new ArrayList<>(Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),
            "-b","/dev","-b","/proc","-b",work+":/work","-b",temporary+":/tmp"));
        if (mounts == null || mounts.size() > 8) throw new IOException("Too many runtime provider mounts");
        Set<String> destinations=new HashSet<>();
        List<Path> sources=new ArrayList<>();
        for (Mount mount : mounts) {
            if (mount == null || !destinations.add(mount.destination)) throw new IOException("Duplicate runtime provider mount");
            directory(mount.source);
            for (Path other : Arrays.asList(rootfs,work,temporary,logs))
                if (overlap(mount.source,other)) throw new IOException("Provider mount overlaps runtime or mutable process state");
            for (Path other : sources)
                if (overlap(mount.source,other)) throw new IOException("Provider mounts overlap");
            sources.add(mount.source);
            // Pinned PRoot binding.c interprets terminal ! as no dereference of
            // the guest destination. Never redirect a provider via a guest link.
            args.add("-b"); args.add(mount.source+":"+mount.destination+"!");
        }
        if (presentation != null) {
            List<Path> ipc=Arrays.asList(presentation.endpoints,presentation.x11);
            for (Path path : ipc) {
                directory(path);
                for (Path other : baseDirectories) if (overlap(path,other))
                    throw new IOException("Presentation IPC overlaps runtime or process state");
                for (Path other : sources) if (overlap(path,other))
                    throw new IOException("Presentation IPC overlaps immutable providers");
            }
            if (overlap(ipc.get(0),ipc.get(1))) throw new IOException("Presentation IPC directories overlap");
            args.add("-b"); args.add(presentation.endpoints+":/session!");
            args.add("-b"); args.add(presentation.x11+":/tmp/.X11-unix!");
        }
        args.addAll(Arrays.asList("-w","/work","/usr/bin/env","-i"));
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
    private static boolean overlap(Path first,Path second) { return first.startsWith(second) || second.startsWith(first); }
    private static void directory(Path path) throws IOException {
        if (!path.isAbsolute() || !path.normalize().equals(path) || path.toString().indexOf(':')>=0 ||
                Files.isSymbolicLink(path) || !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !path.toRealPath().equals(path))
            throw new IOException("Process directories must be existing canonical directories");
    }
}
