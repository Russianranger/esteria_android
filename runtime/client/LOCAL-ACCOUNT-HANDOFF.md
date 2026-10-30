# Private normal-login handoff

Client revision `471ee42faadf4a97a1d0a86989cf1452621f2dc5` advertises the
source-owned `local_account_handoff` capability. Its five-job client build
41061576677 passes, including native x64/ARM64 Win32 file-consumer tests and
native ARM64 Wine component tests. These are not asset-backed Glue/world tests.

The Android adapter requires the exact capability in both the provider and
hash-verified installed build manifest before returning `--local-offline` and
`--local-login`. Older clients gain no capability from a launcher update. The
provider preserves old-client package output by omitting this optional field.

The session owner first prepares an owned client launch view, verifies its
provider generation, and establishes the ordinary owned account and local
services. `prepareLocalLogin` copies credentials into a private0600, exclusively
created executable-sibling `Esteria-local-login.bin`: eight ASCII bytes ESTLOGN1,
16 random nonce bytes,17 account bytes,16 password bytes; total57. Credentials
are not arguments, environment variables or public receipts. Callers clear their
own input arrays. Temporary writer/readback buffers are cleared.

The client waits for real Glue/login readiness and accepted agreements, consumes
and deletes the file before using its ordinary login path. It does not bypass
agreements or start CommonMain diagnostics as gameplay. Source support does not
qualify actual normal login without game data.

Retain the returned handoff handle until the client has stopped. Cleanup removes
only its same-inode, single-link, private, unchanged file; absence means consumed.
Construction failures remove only the exact owned record or written prefix.
Changed/replaced/linked files are preserved and reported. Interrupted files are
never overwritten. PRoot bindings and same-UID storage are not a security boundary.

Host filesystem contracts pass at32MiB, including construction failure/retry,
consumed cleanup, foreign-file preservation and settings preservation. Android
instrumentation now includes the same contracts on real app-private storage;
Android/normal login qualification remains pending its actual result. Main START
remains gated until the complete owned gameplay session exists.
