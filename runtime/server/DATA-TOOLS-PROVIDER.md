# Qualified ordered data-tool provider

The distinct `server-data-tools-arm64` selection now admits the actual ordered
map/vmap readers and unchanged original assembler/navigation programs. It does
not replace or repin the historical stock extractor provider. Android packaging
chooses one profile; `serverExtractorsProviderDir` and `serverDataToolsProviderDir`
are mutually exclusive.

Actual native ARM64 run 41103915829 at 64dd9bc uses the exact published Ubuntu
21a9e802 dependency image. It passes all five original CLI/configuration cases,
two source-supported capability responses and 22 actual stripped-reader lookup
tests with zero skips. The final archive is 2,902,474 bytes, SHA256
`21ce4e1b9a4ff054df4a781cf6b83f37149ab941014d2759f33d93bbfebf231b`.
Its 81 regular members contain8,945,245 bytes. All 66 original notices, original
stock tool/debug pairs and mmaps YAML remain unchanged; the integration license
is added separately.

The ordered source archive, original source bindings, paired ordered debug and
original stock debug have all been independently read back, including every
member hash and mode. Source/debug companions remain outside APK assets.
`runtime/evidence/server-data-tools-provider-41103915829.json` retains the raw
native receipt and measured readback boundaries. GitHub's run/job status was
still inconsistent with its completed logs and retained outputs when recorded;
that evidence does not claim confirmed whole-workflow completion.

To consume these exact outputs without rebuilding the worldserver:

```sh
python3 tools/prepare_data_tools_provider.py acquire --output out/data-tools-qualified-inputs
python3 tools/prepare_data_tools_provider.py build --inputs out/data-tools-qualified-inputs --output out/data-tools-qualified
python3 tools/provider_server_data_tools.py verify --provider out/data-tools-qualified/provider
```

Acquisition requires supported GitHub authentication and at least 1 GiB free. Both
artifact and selected member identities are pinned in
`data-tools-qualified-artifacts.lock.json`. The build independently reproduces
the measured admission pin before creating its install descriptor. It performs
full source/debug verification again. These Actions inputs expire; durable
preservation is required before releasing a final user package.

Package with the verified Ubuntu dependency provider:

```sh
./gradlew :app:clean :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug \
  -PserverRuntimeProviderDir=/absolute/dependency-provider \
  -PserverDataToolsProviderDir=/absolute/out/data-tools-qualified/provider
python3 tools/provider_server_data_tools.py verify \
  --provider out/data-tools-qualified/provider --apk app/build/outputs/apk/debug/app-debug.apk
```

On the host, the actual Java runtime installer has installed all 81 members under
`-Xmx32m` and reused the completed generation with zero copied bytes and no archive
required on reuse. The real SDK build, Android test APK and lint passed in 39 seconds (82 tasks); final provider verification rechecked all source/debug archives and both stored APK asset bytes. None of
these results establishes Android guest execution, extraction of user MPQs,
geographical coverage, custom Esteria data order, world entry or gameplay. Those
flags remain false. No maps, DBCs, vmaps, mmaps, Cameras or shaders are supplied by
this provider; real imported12340/custom data is still required.
