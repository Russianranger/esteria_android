# Private initialization diagnostics

The matched-client reference currently stops before SQL while initializing a
fresh MySQL instance. Its bounded public receipt identifies errno17/EEXIST from
creating the already-owned staging directory after an earlier directory read
failed. Existing empty datadirs are valid for MySQL initialization; this error
alone does not identify the original directory-read failure or establish an
AppArmor, permission, temporary-directory or protocol cause.

The separate offline CI tool overlay now adds ARM64 strace6.8-0ubuntu2 from the
same signed Ubuntu noble snapshot index used by its32 original solved packages.
The477,478-byte DEB SHA256 is
`41a1f7409e46251b6e66db834456cbda1e4f0bf58c52d015a0130630f6ef0a24`.
Its only dependency, libc6>=2.38, is already supplied by the exact unchanged
base2.39-0ubuntu8.9. The original solver record remains a32-package historical
record; diagnosticAddition separately records this signed-index addition. No
resolver, APT update or base replacement is performed by the offline image build.

All three original strace source files are hash-pinned from the signed source
index and retained with the other67 source inputs. Actual local staging/readback
of33 package inputs and67 source files passes; no ARM64 diagnostic execution is
claimed from this host. The package remains test-only, outside the application.

The diagnostic harness must preserve the original failure and failed state,
execute any trace only in a separate owned fresh fixture, bound private output,
and export fixed syscall/errno/path-role classifications. Raw paths, SQL, logs
and credentials must remain private. A successful traced run does not qualify an
untraced client/server session. Keep read-only root and external-network isolation;
do not disable security policies or move binaries to evade them.
