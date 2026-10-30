# Optional extractor installer

The measured payload from build `41019374697.1` is 2,495,044 compressed bytes,
76 regular files and 7,423,422 installed bytes. Its four fixed ARM64 tools and
original mmaps YAML passed native argument/configuration validation in workflow
`41054451870`. `server-extractors-cli-41054451870.json` records the exact runtime,
paired debug, source, original notices and native receipt identities.

`tools/provider_server_extractors.py audit --package <package> --native-cli
<extractor-cli.json>` fully verifies this retained payload without executing it.
The original 66 source/Lua notices stay in the runtime archive. Four paired debug
files, compile commands, original provenance and packaging recipes stay outside
the APK in the separate debug archive.

The production pin remains `pending-sealed-source-rebuild`. Both `build` and
`verify` refuse production output until the actual shared isolated source rebuild
completes. A source boolean change is insufficient: an updated reviewed pin must
contain the exact complete archive, sealed receipt and qualification identities.
The helper reads the entire source archive and paired extractor debug archive,
checks their original source/build/module bindings, requires all four extractor
targets in the actual successful full rebuild and keeps original unsealed
receipts unchanged. It uses the same complete source companion as server
programs, without requiring the three server-program debug files for extraction.

Once those real inputs exist, the build interface is:

```
python3 tools/provider_server_extractors.py build \
  --package <measured-package> --native-cli <extractor-cli.json> \
  --sealed <actual-isolated-sealed-directory> \
  --debug-archive <server-extractors-debug-arm64.tar.gz> --output <new-provider>
```

The provider contains only `assets/server-extractors/{provider.json,
server-extractors.archive}` and a separate `sources/` companion. APK verification
checks the exact two asset byte streams and requires ZIP_STORED for `.archive`.
The source and debug companions are not Android assets.

The Gradle property is `serverExtractorsProviderDir`; its default is absent and
`SERVER_EXTRACTORS_PACKAGED` is false. The optional profile requires production
ARM64 and the separately verified Ubuntu dependency provider. The reviewed pin
must be sealed before Gradle accepts a directory. It rejects emulator fixture
profiles and verifies the complete provider before building.

`ServerExtractorsSetup` uses the existing bounded installer, embedded archive
cache, full 76-file hash plan and ELF183 checks in canonical private storage.
Installation resumes/caches atomically and starts no process. The package key is
`server-extractors-arm64`; the fixed guest mount is `/esteria-server-extractors`.
Only the four `Tool` enum values expose executable paths. `configurationPath()`
returns `/esteria-server-extractors/etc/mmaps-config.yaml`; callers must pass it
explicitly. The descriptor binds the exact original YAML, four program/debug
pairs, packaging pin, native CLI receipt, source qualification and required
Ubuntu runtime archive. Installation consumes no arbitrary executable path.

Native CLI validation is not conversion qualification. The stock MPQ order and
loose-provider gap described in `EXTRACTOR-PACKAGING.md` remains. No client MPQs
were supplied, custom Esteria extraction remains disabled, and Android execution,
conversion, appearance and gameplay are unqualified. This batch does not add a
source patch or application process/service/launch wiring.
