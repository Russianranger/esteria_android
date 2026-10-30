package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.Map;

/** Argument/path behavior only; these fixtures never pretend to execute PRoot. */
public final class ProotMountTests {
    @FunctionalInterface private interface Action { void run() throws Exception; }
    private static void check(boolean value,String reason) { if (!value) throw new AssertionError(reason); }
    private static void rejects(Action action) throws Exception {
        try { action.run(); }
        catch (IOException | IllegalArgumentException expected) { return; }
        throw new AssertionError("Unsafe launch was accepted");
    }
    private static final class Fixture implements AutoCloseable {
        final Path base=Files.createTempDirectory("esteria-mounts-").toRealPath();
        final Path runtime=Files.createDirectory(base.resolve("runtime")), work=Files.createDirectory(base.resolve("work")),
                temp=Files.createDirectory(base.resolve("temp")), logs=Files.createDirectory(base.resolve("logs")),
                data=Files.createDirectory(base.resolve("data with spaces")), binary=Files.createDirectory(base.resolve("client"));
        final Path tracer=executable("proot"),loader=executable("loader");
        Fixture() throws IOException { }
        private Path executable(String name) throws IOException {
            Path file=Files.write(base.resolve(name),new byte[]{1});
            Files.setPosixFilePermissions(file,PosixFilePermissions.fromString("rwx------"));return file;
        }
        OwnedProcess.Specification create(List<ProotLaunch.Mount> mounts) throws IOException {
            return ProotLaunch.create(tracer,loader,runtime,work,temp,logs,List.of("/work/client/WowClient64.exe","one argument"),
                    Map.of("WINEPREFIX","/work/wine"),mounts);
        }
        @Override public void close() throws IOException {
            try (var paths=Files.walk(base)) {
                for (Path path:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
    public static void main(String[] args) throws Exception {
        try (Fixture fixture=new Fixture()) {
            OwnedProcess.Specification spec=fixture.create(List.of(new ProotLaunch.Mount(fixture.data,"/esteria-data"),
                    new ProotLaunch.Mount(fixture.binary,"/esteria-client")));
            check(spec.arguments.contains(fixture.data+":/esteria-data!"),"Space-containing source must remain a single argv element");
            check(spec.arguments.contains(fixture.binary+":/esteria-client!"),"Guest destination must not follow links");
            check(spec.arguments.indexOf(fixture.data+":/esteria-data!")<spec.arguments.indexOf("/usr/bin/env"),"Bindings precede command");
            check(spec.arguments.get(spec.arguments.size()-1).equals("one argument"),"Guest argument preserved verbatim");
            check(spec.environment.get("PROOT_LOADER").equals(fixture.loader.toString()),"Installed native loader retained");
            check(spec.arguments.contains("WINEPREFIX=/work/wine"),"Explicit guest environment retained");
            check(!fixture.create(List.of()).arguments.contains(fixture.data+":/esteria-data!"),"No implicit data exposure");
            check(fixture.create(List.of(new ProotLaunch.Mount(fixture.binary,"/esteria-shader-tools")))
                    .arguments.contains(fixture.binary+":/esteria-shader-tools!"),"Fixed shader tools binding is explicit and does not follow guest links");
            rejects(()->new ProotLaunch.Mount(fixture.binary,"/esteria-shader-tools/tools"));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(fixture.work,"/esteria-shader-tools"))));

            for (String target:List.of("/", "/work", "/tmp", "/proc", "/dev", "/usr", "/esteria-data/child", "/esteria-data!"))
                rejects(()->new ProotLaunch.Mount(fixture.data,target));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(fixture.data,"/esteria-data"),
                    new ProotLaunch.Mount(fixture.binary,"/esteria-data"))));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(fixture.data,"/esteria-data"),
                    new ProotLaunch.Mount(fixture.data,"/esteria-client"))));
            Path nested=Files.createDirectory(fixture.data.resolve("nested"));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(fixture.data,"/esteria-data"),
                    new ProotLaunch.Mount(nested,"/esteria-client"))));
            for (Path protectedPath:List.of(fixture.runtime,fixture.work,fixture.temp,fixture.logs,fixture.base))
                rejects(()->fixture.create(List.of(new ProotLaunch.Mount(protectedPath,"/esteria-data"))));
            Path mutableChild=Files.createDirectory(fixture.work.resolve("child"));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(mutableChild,"/esteria-data"))));
            rejects(()->ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,mutableChild,fixture.logs,
                    List.of("/bin/true"),Map.of()));
            Path nestedLogs=Files.createDirectory(fixture.temp.resolve("logs"));
            rejects(()->ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,fixture.temp,nestedLogs,
                    List.of("/bin/true"),Map.of()));
            rejects(()->ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,fixture.temp,fixture.temp,
                    List.of("/bin/true"),Map.of()));
            Path symlink=Files.createSymbolicLink(fixture.base.resolve("data-link"),fixture.data);
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(symlink,"/esteria-data"))));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(symlink.resolve("nested"),"/esteria-data"))));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(fixture.data.resolve("../client"),"/esteria-data"))));
            Path colon=Files.createDirectory(fixture.base.resolve("colon:source"));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(colon,"/esteria-data"))));
            rejects(()->fixture.create(List.of(new ProotLaunch.Mount(Path.of("relative"),"/esteria-data"))));
            Path endpoints=Files.createDirectory(fixture.base.resolve("ipc")),x11=Files.createDirectory(fixture.base.resolve("x11"));
            ProotLaunch.PresentationBindings shared=new ProotLaunch.PresentationBindings(endpoints,x11);
            OwnedProcess.Specification presentation=ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,
                    fixture.temp,fixture.logs,List.of("/usr/bin/Xtigervnc"),Map.of(),List.of(),shared);
            check(presentation.arguments.contains(endpoints+":/session!")&&presentation.arguments.contains(x11+":/tmp/.X11-unix!"),"Explicit fixed shared IPC bindings");
            check(presentation.arguments.contains(fixture.temp+":/tmp")&&presentation.environment.get("PROOT_TMP_DIR").equals(fixture.temp.toString()),"Per-process temp remains isolated");
            for(Path invalid:List.of(fixture.work,fixture.temp,fixture.logs,fixture.runtime,fixture.base,x11))
                rejects(()->ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,fixture.temp,fixture.logs,
                        List.of("/bin/true"),Map.of(),List.of(),new ProotLaunch.PresentationBindings(invalid,x11)));
            rejects(()->ProotLaunch.create(fixture.tracer,fixture.loader,fixture.runtime,fixture.work,fixture.temp,fixture.logs,
                    List.of("/bin/true"),Map.of(),List.of(new ProotLaunch.Mount(endpoints,"/esteria-bridges")),shared));
            check(fixture.create(List.of(new ProotLaunch.Mount(fixture.binary,"/esteria-turnip"))).arguments
                    .contains(fixture.binary+":/esteria-turnip!"),"Optional Turnip mount only by explicit request");
            rejects(()->fixture.create(null));
        }
        System.out.println("PRoot provider mount isolation and argv checks passed; no guest execution claimed");
    }
}
