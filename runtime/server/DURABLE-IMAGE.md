# Native runtime tests from the preserved dependency rootfs

Runtime-only qualification can use the already published dependency bytes
instead of rebuilding them through APT on every job. This avoids treating a
temporary Ubuntu snapshot HTTP503 as a MySQL or server failure. It does not
change the selected source, MySQL version, libraries or Android provider pins.
The original `Dockerfile` remains the source-build recipe and uses bounded APT
retries with the same signed/hash-pinned indexes.

On a native Linux ARM64 Docker runner:

```sh
python3 tools/release_server_dependencies.py prepare --output out/dependency-release
python3 tools/prepare_server_dependency_image.py \
  --inputs out/dependency-release --output out/dependency-image
docker build --network none --platform linux/arm64 \
  -t esteria-server-deps:verified out/dependency-image/context
docker image inspect esteria-server-deps:verified --format '{{.Id}}' \
  > out/dependency-image/image-id.txt
docker run --rm --network none --read-only \
  --mount "type=bind,src=$PWD/tools/verify_server_dependency_image.py,dst=/verify-image.py,readonly" \
  --mount "type=bind,src=$PWD/out/dependency-image/context-receipt.json,dst=/context-receipt.json,readonly" \
  esteria-server-deps:verified /usr/bin/python3 /verify-image.py \
  --context-receipt /context-receipt.json \
  > out/dependency-image/image-readback.json
```

`prepare` downloads the exact nine public release assets. The image-context
helper then independently revalidates the published asset identities, complete
GNU tar graph and component ELF identities, package notices and every file in
the corresponding-source ZIP. It copies only the 112,374,096-byte rootfs archive
(SHA256 `21a9e8020aac3c780114e2b3e368a643a6e830d35b6406ed99135dec9ba03ce5`)
and a fixed Dockerfile into a new `context/`. The archive is read back after
copying. Existing destinations, linked input ancestors, overlapping directories
and changed bytes are rejected. No source ZIP, credentials, host checkout or
private state enters the Docker context.

The Dockerfile uses `FROM scratch` and `ADD` of that verified local tar.gz, sets
an explicit standard PATH and `LANG=C.UTF-8`, records the archive hash as a
label, and defaults to Python's version command. It has no RUN instruction,
APT call or external base-image selection. Docker restores the existing archive
modes/links; it supplies `/dev`, `/proc` and its normal per-container identity
mounts on execution. The archive was normalized from a fresh dependency image:
its database/state/content/server trees are empty, and its host resolver/name
files are portable placeholders. Never replace the input with an export from
a running or previously initialized container.

The helper's `context-receipt.json` stays outside the Docker context. It binds
the rootfs, original runtime metadata, source lock, full source companion,
source inventory and Dockerfile. Its image-built, guest-executed, initialized,
Android and gameplay fields remain false. Context generation is not a database
test. The source companion stays beside the release inputs for retention or a
hash-keyed CI cache; a cached copy must still pass verification.

Before using the image, qualification must compare its actual
`/etc/esteria-server-runtime.json` with the measured metadata and verify the
three recorded executable hashes inside the image. The readback command above
also requires native ARM64 Linux, verifies that its running Python is the exact
checked image executable, and rejects initialized database/private-state trees.
Then run the existing fresh
owned-state MySQL/dbimport/auth fixtures with `--network none` and their normal
mounted source/content inputs. Preserve the Docker image ID and context receipt
alongside those execution results. No existing database is adopted, copied into
the image, or overwritten by this workflow.

The local helper tests use synthetic archive bytes to exercise preservation,
copy readback, source-validation requirements and exact context boundaries.
Actual Docker reconstruction and SQL execution remain CI gates.
