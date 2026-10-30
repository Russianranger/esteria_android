# Separate ordered extractor adaptation

This is an extractor-only source recipe. It adds no eighth global server patch,
changes no normal server program identity and does not replace the currently
measured stock extractor provider. The original seven-patch source export,
preparation receipts, compiled-module receipts and full isolated source gate
remain separate.

The source policy is pinned to reconstructed client
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`. Its ordering code is unchanged from
the reviewed `0f` reader; only the account handoff differs in `Client.cpp`.
`extractor-order.lock.json` binds ten exact client files, four original/adapted
tool files, the separate patch, shared reader header, original libmpq/support
headers, planner and patch recipe. Client policy sources are retained with the
native build payload.

## Supported order

`runtime/extractor_order.py` plans the normal, nontrial, nonstreaming classical
profile with a single owned `Data` root, direct loose access disabled and no
Retail virtual-provider translation. The caller must establish this profile
from its launch view and content selection. Unsupported profiles are refused;
they do not fall back to stock enumeration.

The planner follows `PatchFiles(locale,false)` and `Client.cpp::OpenArchives`:

* Arbitrary `Data/patch-*.MPQ` and selected-locale suffixed patches are sorted
  together by case-insensitive **full Windows path** descending, without numeric
  suffix interpretation. Plain root and locale patches are appended afterward.
* Opening reverses that enumeration and assigns increasing priorities. Effective
  lookup is highest priority first: suffixed patches, plain root, plain locale.
  Root patches sort above `enUS` patches but below `ruRU` patches; locale is not
  a universal override layer.
* The exact 29-entry base table determines base priorities. `common.MPQ`,
  `common-2.MPQ` and appended `common-3.MPQ` have priorities 47, 46 and 38.
* A physical `alternate.MPQ` base opens above direct patches. Each patch's
  `alternate/` view opens above that base and preserves patch precedence. Chinese
  locale exceptions create views even without the alternate base. Regular MPQ
  views may be empty; a folder patch view requires a physical `alternate` child,
  which may itself be a folder or an MPQ file without an extension.
* The configured locale rotates through the exact client locale table until a
  regular locale archive is found. A folder `common.MPQ` or locale archive does
  not activate classical/locale availability. Folder **patch** providers are
  supported and participate in the same ordering as archives.

The JSON manifest records rank, priority, effective locale, provider path/kind,
optional prefix view and exact input identities. The hash-bound wire projection
is highest-first and contains no absolute input root. Folder entries have a
closed case-insensitive file inventory with file size/SHA256 pins.

## Explicit reader mode

The separate patch changes only map/vmap entry points and their two MPQFile
constructors, adding the shared header at `src/tools/EsteriaArchiveOrder.h`.
Without ordered arguments, the original desktop path stays in use. Ordered mode
requires all three arguments:

```
--esteria-order <wire.tsv> --esteria-input-root <owned-root> \
--esteria-order-sha256 <exact-wire-sha256>
```

It forbids conflicting legacy `-i`/`-d` input selection. Map, DBC and camera
reads use the same selected stack and effective locale. The native fixture gate
uses `--esteria-order-member-probe` to exercise the **actual patched MPQFile
constructor**, plus `--esteria-order-list`; neither converts game data.

Both readers check archive identities, directory inventories and selected loose
file hashes. They resolve neutral locale/platform hash records like the normal
client handle. A delete marker stops lookup instead of falling through. Zero and
one-byte members remain files. A decode error never returns a lower archive's
bytes. Non-ASCII/ambiguous case paths, links, unsupported archive dialects, delta
patches and selected encrypted file payloads are explicitly refused. The pinned
libmpq decoder cannot reliably derive keys for every encrypted file layout;
encrypted tables in ordinary MPQs are supported, while encrypted file payload
qualification is intentionally absent.

The stock converter's output-format and asset coverage requirements still apply.
This work does not prove complete MPQ listfiles, modern asset translation,
canonical output filename coverage, map/collision correctness or valid custom
Esteria appearance data. Real client assets are absent. Conversion, custom-data,
Android, world entry and gameplay qualification remain false.

## Reproducible build boundary

`prepare_ordered_extractors.py` copies a fresh asset-free seven-patch preparation,
applies the separate exact patch and preserves original preparation receipts.
The new native workflow acquires only the retained 18 MB source inputs and
original compiler metadata, plus ten small client policy files. It checks the
same relevant native compiler/development environment, enters a loopback-only
network namespace and builds only `map_extractor` and `vmap4_extractor` with two
compiler jobs and no cache. Normal auth/world/dbimport and the two other stock
tools are not requested or replaced.

The workflow runs synthetic archive/folder tests against both actual newly built
programs, retains source inputs, patch/header, policy sources, recipes, compiler
commands/environment, unstripped binaries and typed receipts separately. These
are not APK assets. The recipe inventory is a selected subset; imported helpers
and the isolated build lock are supplied by the recorded integration revision.
This artifact is not a complete source companion. A later measured strip/debug derivative and provider rebind
requires actual native results and the corresponding source gates; pending flags
are not flipped by these host tests.
