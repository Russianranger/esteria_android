# Android x64 installation coordinator qualification

This is an internal Android13 x64 execution gate for the existing Java
installation coordinator. It cannot qualify production ARM64, Thor, game data,
world entry, character saving or bot AI. The measured x64 source and native SQL
selection remains disabled until actual successful build, complete-source and
four-schema SQL receipts exist. Missing measurements must refuse before download,
APK payload preparation or database initialization.

## Boundaries to preserve

The public constructors of `ServerRuntimeSetup`, `ServerProgramsSetup` and
`ServerContentSetup` keep their current ARM64/provider checks. The production
`InstalledProot` locator and ARM64 helper receipt admission remain unchanged.
No x64 executable receives an ARM64 receipt or production provider identity.
No reflection writes coordinator state, no substitute SQL loader executes, and
no caller Intent/path/Boolean grants qualification authority.

The x64 component contains only the original compiled `dbimport` target and real
Playerbots schema helper, with their original ELF62, split debug, captured loader
and full library/source closure. It contains no invented auth/world programs.
The public architecture-neutral SQL content retains its original ARM64 packaging
origin. The fixture records that origin separately from its genuine x64 runtime.

## Small production seam

Five implementation files need a narrowly shared internal path:

1. `ServerInstallationSetup.java`: package-private typed `InstalledInputs` and a
   private production adapter. Existing public methods construct that adapter.
   The retained Handle, fresh workspace, phase transitions, result checks,
   clean-stop proof and promotion stay shared. The contract supplies admitted
   immutable selections and source-owned helper policy; it does not accept a
   completed-state Boolean or fabricated result.
2. `ServerDatabaseSetup.java`: package-private installed-runtime overload for
   bootstrap on a retained `FreshServerInstallations.Workspace`. Existing public
   methods use the production runtime adapter.
3. `ServerDatabaseService.java`: extend its existing package-private
   `InstalledRuntime` seam for archive-bound fresh/active workspaces and plain
   helper launches. Keep the same actual service owner, JNI child, ready lease,
   shutdown command and stopped-receipt checks.
4. `ProotProcess.java`: typed, fixed-asset qualification payload selection and
   package-private launch overloads. Only a separately enabled debug profile with
   a compiled exact provider pin can inspect the original measured x64 Bionic
   PRoot payloads in `nativeLibraryDir`. Recheck those bytes before every launch.
   Ordinary entry points still use the unchanged ARM64 `InstalledProot.inspect`.
   Both routes use the same path/mount checks, `ProotLaunch` and native owner.
5. `runtime/android_server_installation_setup.py`: private shared finish/run
   kernels. Public entry points and CLI keep the fixed current ARM64 admission.
   A fixture-only wrapper may supply a real, fully admitted x64
   `playerbots.Preparation`; all existing staged/configuration/journal/credential
   checks, `playerbots.apply`, verification and finish receipts remain shared.

The x64 adapter's authority comes from an exact compiled provider pin plus
measured source/build/native-SQL receipts, never from merely implementing an
interface. The normal APK does not package or expose this adapter. There is no
production guard that accepts machine183 or machine62 interchangeably.

## Qualification-only files

- `app/server-installation-probe.gradle`, applied by `app/build.gradle`, adds
  default-disabled BuildConfig pins and a debug-only x86_64 provider. It refuses
  release builds and incompatible production providers. No positive provider can
  be generated from the current disabled/null SQL input selection.
- `tools/provider_android_installation_x64.py` and its focused Python tests build
  and re-read the exact source/debug/native-SQL-bound payload and helper manifest.
  Actual original sources remain beside the build; no database or secret enters
  the APK or source companion.
- `app/src/androidTest/java/io/github/russianranger/esteria/runtime/InstallationX64Inputs.java`
  implements the typed admitted selection using the exact APK provider pin.
- `app/src/androidTest/java/io/github/russianranger/esteria/runtime/ServerInstallationX64Test.java`
  runs fresh core setup, real fourth schema, clean promotion, completed readback,
  active-save reseeding refusal, same-instance restart, actual SQL/journal
  preservation and a second clean stop.
- `tests/android-installation-x64/installation_x64_entry.py` is the source-owned
  guest wrapper. It admits the genuine new x64 proof scope and calls the private
  shared production kernels. It does not monkeypatch ARM64 admission functions.
- `.github/workflows/android-server-installation-x64.yml` first checks the measured
  gate, then prepares assets and executes the actual Android13 x64 fixture.
  Pending selection is reported as unexecuted, not successful installation.

This checkpoint implements the typed Java seam, private Python kernels,
default-disabled fixed-payload inspector and measured input-selection gate. The
provider builder, Android inputs adapter, actual instrumentation and Android
workflow listed above are follow-through work. No positive x64 provider exists.
After native SQL qualification, a separate measured-native/provider-pending
state may permit provider measurement only; actual descriptor SHA and independent
readback must be committed before APK execution can be enabled.

Native qualification invocation scripts contain native fixture paths. Android's
new source-owned invocation scripts therefore receive separate identities. Their
admission binds the unchanged actual ELF and captured library/loader identities
to the positive native SQL receipt; it never relabels a different script as the
original SQL-qualified executable. Android execution is a new gate.

## Validation before publishing the seam

Run existing Core fresh-installation and app installation/service/owner fixtures,
focused Python installation/Playerbots tests, Java/AndroidTest compilation and
lint. Add negative tests for foreign/missing proof, machine mismatch, changed
helper/receipt/content/runtime and pending execution refusal.

Rerun the current equivalent of native ARM64 Java gate41109643068 after the
refactor. It must still execute real core/four-schema SQL, clean promotion and
restart through the production adapter. Host tests and a compiled debug fixture
cannot replace that regression gate. Actual Android x64 execution additionally
requires the future positive native x64 measurements; no Thor probe is requested.
