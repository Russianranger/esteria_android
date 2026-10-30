# Exact engine derivative reference workflow

`server-engine-package.yml` processes the retained seven-patch build
`41019374697.1` from integration `e9dcb61d8d8c40fc683ac2a67bbf15a8eb538300`.
`engine-reference.lock.json` fixes its installed, content and diagnostic artifact
IDs, lengths and hashes. The original workflow passed linking, install, loader,
module selection and content packaging, then failed the runtime step. That
failure remains explicit; retaining its valid build outputs does not qualify SQL.

The Linux x64 job requires 12 GiB free before any artifact API call or download.
It streams and independently reads back all three ZIPs before extracting them,
rechecks the current seven-patch source lock and actual module literals, and
repackages content from the exact source. Existing output is never reused.
The locked NDK objcopy is extracted alone from its fully verified upstream ZIP;
its original notices are retained. No AArch64 input executes in this job.

The actual authserver, worldserver and dbimport receive separate debug files and
stripped runtime derivatives through the reviewed packager. Mapped bytes, symbols,
debug sections and debug links are checked against the originals. Both archive
inventories are fully read back before publication. No original build or module
receipt is rewritten.

CI retains three separate artifact groups for 30 days:

| Artifact | Contents | Qualification |
| --- | --- | --- |
| Runtime | Stripped programs, immutable configurations, original provenance, paired receipt and exact SQL/content package | Internal native reference input |
| Debug | Separate symbols, strip recipes, paired receipt and original NDK notices | Paired to the exact runtime hashes; outside any APK |
| Source inputs | Selected pristine Git code/notices, full Eluna tree, exact indexed adaptations, original Lua archive and build recipe inputs | Unsealed; isolated source rebuild and complete closure remain open |

The native ARM64 job binds both runtime and content receipt hashes to producer
job outputs before extraction. It reconstructs the exact published Ubuntu/MySQL
image with `FROM scratch`, `--network none`, full source revalidation and actual
image metadata/ELF readback. Runtime gates run inside that image, with the
checkout/runtime inputs mounted read-only and a new disposable state directory.

The first execution gate runs derived auth/world `--version` only. The second
uses `qualify_authserver.py --engine-derivative-receipt ...` to execute the actual
derived dbimport twice, check schema/ledger persistence and restart, and exercise
owned loopback auth/SRP. The explicit derivative selector returns the original
build unchanged alongside separately verified runtime program identities. It
cross-binds the content module receipt to the original module/build hashes and
checks selected bytes immediately before execution.

Only typed receipts, bounded host logs and existing redacted SQL/auth diagnostics
are uploaded. Private database/configuration/account state is retained only in
the disposable runner. A failed gate does not become a successful server result.
No job creates an Android provider, changes a source lock, adopts saved state,
starts a world session or establishes Android/gameplay readiness. Source closure
flags remain false even when the derivative/native reference gates pass.
