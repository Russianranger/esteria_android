# Optional schema-helper programs profile

The stock `programs-provider.lock.json` remains unchanged. Explicitly select
`serverProgramsProfile=playerbots-schema-helper` with a provider built against
`programs-playerbots-provider.lock.json` to package the original three programs
plus the separately source-sealed `playerbots-schema` initializer. This is an
installation profile, not evidence of Android server execution or in-world AI.

The measured augmented runtime is30,730,491bytes, SHA256
`963a23c1390440260b85ffe164b2d7508c56b005b315dce8a919ae443a46d1bf`.
Its131 members expand to92,638,681bytes, within the original96MiB policy.
Every original126 member, three executable/debug pair, native loader receipt
and66 notice file stays unchanged. The five additions are the original b7
helper, its original build and native SQL receipts, its sealed source receipt
and the initial integration recipe's GPL license. Sources and original paired
debug stay outside APK assets.

The helper's native SQL result applies to the original25,188,512-byte b7
executable from41076505231. The separately observed f327 executable has not
passed that SQL gate and is never substituted. The helper source companion
from41099467799 records that distinction; neither identical object bytes nor
observation of the original helper's compiler process is claimed.

Reproduction from an authenticated development checkout:

```sh
python3 tools/qualify_server_providers.py acquire --output out/stock-inputs
python3 tools/qualify_server_providers.py build --inputs out/stock-inputs --output out/stock-providers
python3 tools/qualify_playerbots_programs.py acquire --output out/helper-inputs
python3 tools/qualify_playerbots_programs.py build --stock-providers out/stock-providers \
  --inputs out/helper-inputs --output out/helper-providers
```

Acquisition verifies exact workflow/artifact identities, streams authenticated
archives and restores only the closed candidate's original modes. The new
factory repeats the original stock provider's full corresponding-source and
paired-debug verification before and after copying, then checks the complete
helper source closure and exact measured delta. It offers no source-check
bypass and executes no packaged program.

Build with the separately verified Ubuntu dependency provider:

```sh
./gradlew --no-daemon :core:check :app:assembleDebug :app:lintDebug \
  :app:serverProgramsProfileTest \
  -PserverProgramsProfile=playerbots-schema-helper \
  -PserverRuntimeProviderDir=/absolute/dependency-provider \
  -PserverProgramsProviderDir=/absolute/out/helper-providers/programs
python3 tools/provider_playerbots_programs.py verify \
  --provider out/helper-providers/programs --apk app/build/outputs/apk/debug/app-debug.apk
```

`playerbots-programs-provider.yml` runs these full source/debug guards, builds
the explicit optional profile, verifies all selected APK bytes and performs a
real host Java32MiB fresh installation followed by zero-copy cached reuse.
Its source/debug, runtime/APK and bounded proof artifacts are separate. Host
decoded-descriptor guard fixtures validate the actual production parser's
closed roles but do not replace Android JSON or AssetManager execution.

`runtime/evidence/playerbots-programs-local-java.json` records a completed
local32MiB Java installation of all131 members/92,638,681bytes and cached reuse
with no archive and zero copied bytes. The exact runtime candidate was fully
read back. This local pass did not invoke the optional provider factory or
reverify the original1.08GB paired-debug companion; the CI gate still requires
those full checks before provider admission.

Passing this workflow qualifies packaging and host archive installation only.
It does not establish Android SQL, slot promotion, normal client login, world
entry, a bot's world login or offline gameplay. The final integrated profile
also needs the source-qualified composed data tools and coherent client/Wine
providers; enabling this explicit profile alone does not open the game gate.
