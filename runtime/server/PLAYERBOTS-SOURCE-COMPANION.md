# Separate Playerbots helper source companion

The separate helper source companion is now sealed. [Workflow 41099467799](https://github.com/Russianranger/esteria_android/actions/runs/41099467799) succeeded at integration revision `9aa691435740f188a987eacf822447ec7fdb70bc`. It authenticated the existing measured inputs, reconstructed their prepared sources, read back the retained compiler/linker dependency observation, and produced a fully read-back source archive. It ran no compiler, helper, SQL engine or Android provider.

The compact [seal evidence](../evidence/server-playerbots-helper-source-sealed-41099467799.json) records the actual positive receipt fields without duplicating its 6,372-member inventory. `sourceCompanionComplete` and `helperSourceCompanionComplete` are true for this separate helper corresponding-source component. They do not activate a provider or qualify phone execution, world entry, bots or gameplay.

## Exact retained output

| Component | Bytes | SHA-256 |
| --- | ---: | --- |
| Source archive | 108,559,554 | `eb7d1a77484943ad2e16d022877671426c28e4e3d7e3d8a1b166073950fc5c0f` |
| Sealing receipt | 1,320,302 | `633cfa8f18bb887249d643b7eaf249e1bfe7bd30daf572e18084574ca8ec046d` |
| Retained source artifact ZIP | 109,880,204 | `96dbf23fbfe9640528fdce28e71bd8ac0c5ffc261dd5124d7f8a24bf723587ae` |
| Evidence artifact ZIP | 325,194 | `693c221e814d0e1acb5565f1352f68792f040c6126baa5560e3935264d60aeb2` |

Source artifact `12997208259` contains `playerbots-helper-complete-sources.tar.gz` and `playerbots-source-receipt.json`. The archive has 6,372 normalized regular-file members containing 440,875,864 file bytes. Its complete inventory stays in the pinned sealing receipt. The receipt has scope `complete-playerbots-helper-corresponding-source-companion`, with `archiveReadbackVerified=true`.

The CI producer performed a full normalized archive readback before atomic publication. A separate local session readback with `tools.package_server_engine.verify_archive` also passed against all 6,372 members and the pinned receipt. That large readback was not repeated to write the compact record. Evidence artifact `12997896206` was independently checked for its outer hash, CRC, exact three-member inventory, declared hashes, input bindings and equality with the retained local source receipt. GitHub metadata confirms both artifact pins and the exact successful producer revision. The source-only acquisition reached phase `complete`; its public failure map is empty.

## Original runtime and source bindings

The runtime helper remains the original 25,188,512-byte executable, SHA-256 `b7d9b72c17f32294915f0a474283c543057ffb7de7b3f93015c2e7e179bfcf25`. Its build receipt (`82b9c7c852164f303500214e044f07bf5eb389fa2f3f03b9f6cdc962a5bba602`) and actual native SQL receipt (`56288b2ea7046fa256bdd53113701bd59236d5d8403a3a16f32b5fcf0ab53c42`) remain unchanged. The registered [helper candidate](PLAYERBOTS-HELPER-CANDIDATE.md) and [native installation finish](NATIVE-INSTALLATION-FINISH.md) identify those existing measured inputs.

The seal keeps the archived 2,170-byte source lock `5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`, full server commit `f35f04d01689f034778e3474b3c820092f51e461`, pinned Eluna commit and all seven patches. Original build `cdfd2ea0361f7dbb54b6f820a4cb295eb6b87fdcda32fe5cf4206ac3fe919d31` and module receipt `6459b6a1acab2c62c474e4c6ab3eb651daa21f697ccd628e93a38bad298bbdd1` remain bound to those sources. The original three-program source archive (`9f76881f06a7c998e0dba9d4a226c623021ed6ad8b87074aa7a861eafbb96d80`), qualification and sealing receipt are retained unchanged in their own namespace.

The separate [native source observation](PLAYERBOTS-SOURCE-OBSERVATION.md), run `41095126547` at `9d20c3bea4f9f2ea7cdfb0915cef1b7ed23faab6`, supplies actual dependency coverage: 201 ARM64 compiler objects, one ARM64 final link, 527 project files, two generated headers, 2,246 system headers, ten local link inputs and 30 system link inputs. Its actual DatabaseLoader, DBUpdater, PlayerbotsDatabase and reference units, `MOD_PLAYERBOTS` definitions and 52-statement header were verified. Its new 25,189,160-byte executable is `f327179c8467e51afe18d3542fad9186551474c69fae541db3f0461eac5a9542`; the old SQL qualification is not transferred to that different executable.

The composer checked exact original/new prepared source, reference inputs, CMake options and compiler identities, and replayed preparation from the authenticated acquired source archive and supplemental header. It then independently read the captured source/object/final-link metadata. Source correspondence is explicit; bit-identical executable output and observation of the original native objects remain false. The source archive does not contain original native object or link-input bytes, or copied system header/library sources.

## Archive contents and replay

The archive retains reconstructable acquired inputs, prepared source files and the metadata used to restore original modes during preparation, generated headers, unchanged original and new producer receipts, source coverage, notices and separate committed recipes for the initial helper, native observation and later sealing operation. Genuine empty source files are retained. Native programs, native objects and static libraries are excluded from source members and identified separately. The embedded original three-program source archive and receipts retain their original bytes.

The source-only acquisition checked the measured 206,956,721-byte capture artifact, 40,130,109-byte registered helper candidate and original 24,704,454-byte source-triple artifact before composition. Only the exact initial-helper `6ce7a9f154b11f5e24ce2d228e613f06001b979f` and native-observation `9d20c3bea4f9f2ea7cdfb0915cef1b7ed23faab6` integration recipe commits were fetched before network isolation. Current sealing recipes are retained separately. No original server repository, game assets, paired-debug package or server runtime image was acquired by this sealing job.

The archive's pinned `replay-plan.json` records preparation with the retained original source inputs, supplemental header and archived lock, followed by the archived `build_playerbots_component.py` and explicit helper-only stabilization target. Replay requires a matching native ARM64 toolchain and loopback-only network namespace, but no Git metadata or asset tree. It creates new build output and cannot rewrite the original helper's build or SQL receipt. The native observation driver remains producer evidence; its committed-recipe Git guard was not relaxed.

To repeat source-only composition from authenticated inputs, fetch the exact historical integration recipes first, then run:

```sh
python3 tools/prepare_playerbots_source_companion.py --output source-inputs
python3 tools/seal_playerbots_helper_sources.py \
  --payload source-inputs/native \
  --candidate source-inputs/candidate \
  --original-sealed source-inputs/original/sealed \
  --integration-git-root . \
  --output ../playerbots-helper-sources
```

The output must be new and outside the integration checkout and every input tree. CI uses a fresh directory below its separate runner temporary root. Publishing the positive receipt requires a final recheck of every immutable input and full archive readback.

The optional provider still needs an exact source/archive binding and install-package verification. This source seal creates no Android provider and changes none of the original programs or runtime proofs. Compilation, helper/SQL execution, production activation, phone execution, Java promotion, world behavior, Playerbots AI and gameplay qualification remain false for this sealing operation.
