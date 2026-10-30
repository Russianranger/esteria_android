# Separate source-owned Wine provider cohort

This release schema retains the four rebuilt packages for client471ee42f and
source-owned Winec0e13ed1. It preserves the unchanged original client, guest bridge
and native Turnip ZIPs, the separately measured source-complete Turnip ZIP, full
client/shader source companions and notices, exact input selections, packaging
recipe files and the two public Wine source release identities.

The new client source receipt requires exactly three selected inputs: the app
source lock, measured client input and selected Wine runtime profile. These are
retained under their canonical integration recipe paths. The original public
client source receipt remains unchanged and keeps its historical two input
schema. Both companions must preserve identical original client Git archive and
Xvid source identities. The original client release validator is unchanged.

The provider asset archive contains all four exact asset trees. Consumers must
verify its full inventory and source companions, restore each tree and apply the
same explicit measured locks. The original runtime and complete1.68GB Wine source
ZIP remain in their separately pinned public release; retain both with this
cohort. The source recovery run is distinct from the successful native binary
producer:18 bytes of filtered recipe source were restored from that producer's
retained original Git tree without rebuilding or relabeling a binary.

First publish this recipe, then run `release_wine_cohort.py stage` against that
exact commit and the retained measured outputs to generate the release lock.
The lock pins the producer, all selected inputs, imported packaging recipe files
and every payload. A separate CI checkout of that recipe recovers the original
inputs, reproduces all provider/source archives without compiling or executing a
binary and requires byte-for-byte equality with the reviewed lock.

Publication uses `dependency_publication.DraftPublication`: only an owned UI
draft with the exact target commit and body is accepted. Missing exact assets
may be added. Existing assets are downloaded completely and compared. The tool
cannot create or finalize a release, move a tag, replace an asset or change
repository settings. Public verification checks the actual tag and all stored
bytes. A published receipt is separate from the immutable release lock.

Linux ARM64 component fixtures passed. Android execution, Adreno graphics,
audible output, CommonMain, imported assets, world entry and gameplay remain
unqualified. No APK, credentials, initialized database/prefix or saved state is
included. Production activation and coherent APK byte verification are separate.
