package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Real direct-child execution with bounded, rotating stdout/stderr logs.
 * Runtime entrypoints must exec their final service or supply their own group owner.
 */
public final class LoggedProcess implements SessionSupervisor.Child {
    private final Process process;
    private final Thread drain;
    private volatile IOException logFailure;
    private LoggedProcess(Process process, Path log, long limit) {
        this.process = process;
        drain = new Thread(() -> drain(log, limit), "esteria-log-" + log.getFileName());
        drain.setDaemon(true);
        drain.start();
    }
    public static LoggedProcess start(List<String> command, Path cwd, Map<String, String> environment,
                                      Path log, long logLimit) throws IOException {
        if (command.isEmpty() || !Paths.get(command.get(0)).isAbsolute())
            throw new IOException("Runtime executable must be an absolute path");
        if (logLimit < 4096 || logLimit > 16 * 1024 * 1024) throw new IllegalArgumentException("Invalid log bound");
        Files.createDirectories(log.toAbsolutePath().getParent());
        ProcessBuilder builder = new ProcessBuilder(command).directory(cwd.toFile()).redirectErrorStream(true);
        builder.environment().putAll(environment);
        return new LoggedProcess(builder.start(), log, logLimit);
    }
    private void drain(Path log, long limit) {
        byte[] chunk = new byte[(int) Math.min(8192, limit)];
        InputStream input = process.getInputStream();
        try {
            OutputStream output = Files.newOutputStream(log, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            long written = Files.size(log);
            try {
                for (int count; (count = input.read(chunk)) != -1;) {
                    if (written + count > limit) {
                        output.close();
                        Files.move(log, log.resolveSibling(log.getFileName() + ".previous"), StandardCopyOption.REPLACE_EXISTING);
                        output = Files.newOutputStream(log, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
                        written = 0;
                    }
                    output.write(chunk, 0, count); output.flush(); written += count;
                }
            } finally { output.close(); }
        } catch (IOException failure) {
            logFailure = failure;
            // Continue draining after a full filesystem; avoid deadlocking the service on stdout.
            try { while (input.read(chunk) != -1) { } }
            catch (IOException ignored) { }
        } finally { try { input.close(); } catch (IOException ignored) { } }
    }
    public IOException logFailure() { return logFailure; }
    @Override public boolean isAlive() { return process.isAlive(); }
    @Override public int exitCode() { return process.exitValue(); }
    @Override public void stop(Duration timeout) throws Exception {
        if (process.isAlive()) {
            process.destroy();
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                if (!process.waitFor(3000, TimeUnit.MILLISECONDS)) throw new IOException("Process did not terminate");
                throw new IOException("Graceful shutdown timed out; process was terminated forcibly");
            }
        }
        drain.join(1000);
    }
}
