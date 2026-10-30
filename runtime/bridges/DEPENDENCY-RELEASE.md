# Durable guest helper inputs

The release tool preserves the measured 469,031-byte helper archive from build
`61bf8a134845276cb78430884d557e477ff286aa` without making future builds download its
142 MB Actions wrapper. It retains all 30 pinned binary/source/notice/config files,
including original libXtst source and Debian changes for statically linked code.
The full compiler/build-tool source companion and the separate Wine rootfs source
closure are outside this small package. Android execution and gameplay remain
unqualified by this packaging step.

`runtime/bridges/android-provider.lock.json` remains byte-for-byte unchanged.
New release-only metadata is in `dependency-release.lock.json`. The release tag
identifies provider packaging revision `ae5534d0a9d7fb72c8e5a03dcfc65420c354e7bb`;
the original helper build revision and artifact hashes are separately recorded.
The GitHub release is not yet published; no durable download is claimed yet.

The workflow has three jobs: read-only validation of the original artifact;
upload-only extension of one exact UI-created draft; read-only verification
after authorized publication. It cannot create/move tags, create/finalize
releases, replace assets or alter repository settings. A published incomplete
release is never repaired. Every existing/downloaded asset is checked against
its full hash before publication is recorded. GitHub-enforced immutability is
reported exactly as observed, separately from the publisher's no-overwrite rule.

Create the authorized prerelease draft using the exact full target SHA and tag
from the release lock and the exact body printed by:

```sh
python3 tools/release_guest_bridges.py body
```

The publisher accepts only the web editor's CRLF newline normalization. Publish
the draft after the workflow's `draft-assets-verified.json` proves the complete
stored asset set. Commit the final read-only `published-release.json` into the
lock's `published` field only after successful final verification.

After that receipt is recorded, a clean checkout needs no Actions token or
historical artifact to recover the provider's inputs:

```sh
python3 tools/release_guest_bridges.py fetch --output /cache/guest-release
python3 tools/release_guest_bridges.py export-payload \
  --inputs /cache/guest-release --output /cache/guest-payload
python3 tools/provider_guest_bridges.py build \
  --payload /cache/guest-payload --output /cache/guest-provider
```

Before publication, `stage --inputs original-artifact.zip --output new-candidate`
provides the same validation offline against the existing measured artifact.
Local staging, payload export and provider rebuild reproduced the exact archive
hash `a91e2e7cf74957c7caf2c7e85de2a6ee8952d273b3f5e3f18cecb06127791c39`.
These are packaging checks; publication and authenticated/unauthenticated
download qualification remain pending.
