# Selection catalog import checks

The importer now checks the 16 named Esteria selection catalogs when encountered
as loose files, including folder-provider paths. The source contract is
`WoW/Common/ComponentCore/EsteriaAppearance.cpp::Selection/ReadSelections` at client
`0f931bbade36a4b197725d691b8eff7caea7b3be` (Git blob `ef8d0df2c04b438462b2b9d582fd2a23e69929c2`, SHA256
`912042ba4d49b485ee7525dc69578fedce03878cef2cb65bada6b6b5e8adaa4d`).

Validation reads one 156-byte record at a time: little-endian EHM1 magic,
version 1, at most 16,384 records, declared complete length, gender/kind-specific
bounds, three bounded selectors and NUL-terminated 128-byte paths. This is a
strict whole-catalog check: the reconstructed reader can skip invalid records or
stop on truncation, while setup reports the malformed input and preserves the
active asset generation. Unknown catalog families retain their separate source
requirements; a successful import never asserts custom-feature completeness.

The 24 importer behavior groups pass with a 32 MiB heap, including all six selection
record kinds, unsigned mask fields, malformed headers/counts/selectors/paths,
truncation/trailing bytes, and an actual failed overlay followed by corrected
retry with the previous generation unchanged. Android Java/lint also pass.
Fixtures are synthetic structural inputs, not replacement game assets.

Catalogs inside binary MPQs are not decoded by this check. Effective archive
precedence, texture-bank/LZNT1 payloads, coverage/geometry catalogs, referenced art
and actual appearance transport/rendering still need the matched content package
and runtime validation. No selection files or placeholder appearances are supplied.
