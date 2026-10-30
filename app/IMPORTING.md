# Android document import

The launcher accepts a client folder or ZIP, and later a custom-content folder or
ZIP. Folder selection uses `ACTION_OPEN_DOCUMENT_TREE` with a persisted read grant;
no broad storage permission or filesystem path conversion is needed. Folder files
stream directly into the transactional importer, avoiding a temporary archive copy.

`SafTreeSource` takes one bounded inventory (at most 200,000 documents, 32 path
components, 1,024 UTF-8 path bytes, and the shared 16 MiB estimated metadata budget).
The metadata budget is enforced before retaining provider entries and normally
reaches its limit well before the absolute document-count ceiling. It rejects repeated IDs, cycles, virtual
documents, unsafe names, provider-reported symbolic links and unknown file sizes.
Opaque provider IDs are used only with `DocumentsContract` URIs. A provider that
hides a filesystem symlink behind an ordinary document cannot be identified as such;
this adapter is not a raw-filesystem symlink detector. The Android provider enforces
access to the granted tree.

Known modification times and sizes support interrupted-copy resume without hashing
all completed files again. If any file has no reliable modification time, the shared
importer uses a new request identity and disables cross-operation reuse. The launcher
shows that limitation. Keep the source unchanged during import. Per-file metadata is
checked before and after copying and again before publication; inventoried directory
metadata is also checked. Providers with unknown directory modification times do not
provide an atomic whole-filesystem snapshot.

Only one file stream is open at a time. Cancellation reaches provider queries through
`CancellationSignal` and closes the active input stream. The provider must implement
cooperative cancellation for prompt interruption of a blocked remote operation.
Final game publication and failure recovery remain owned by `GameDataImporter`.

ZIP imports retain bounded archive staging so central-directory safety and CRC checks
can run before publication. Staging plus expanded files needs additional space; folder
imports avoid staging. Prior published generations remain available, and automatic
generation cleanup is not implemented yet.

The generic document-source behavior is host-tested; Android SAF behavior has been
compiled and linted, but has not yet been exercised on an emulator or the Thor.
