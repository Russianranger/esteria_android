# Native playerbots helper source observation

[Workflow 41095126547](https://github.com/Russianranger/esteria_android/actions/runs/41095126547) succeeded at integration revision `9d20c3bea4f9f2ea7cdfb0915cef1b7ed23faab6`. It compiled only `esteria_playerbots_database_reference` on native ARM64, performed a second same-target build to stabilize generated metadata, and recorded the actual Ninja object and final-link dependency graph. The selected new helper was not executed against MySQL.

The compact retained [evidence](../evidence/server-playerbots-helper-source-observation-41095126547.json) copies the measured qualification fields and records the boundary of the independent evidence readback. This is a successful target compile and source-dependency observation. It is not a completed helper source companion or a production-provider admission.

## What ran

The initial configure returned zero in 4.638 seconds. The actual helper compile returned zero in 116.729 seconds; the second same-target build returned zero in 0.121 seconds. Both compiler-launcher cache entries were empty, compiler caching was disabled, and the build namespace exposed only loopback. The full CMake project was configured with the archived original options; only the requested helper target was built. No original server program was rebuilt or replaced.

The helper uses the actual database sources and the 52-entry playerbots prepared-statement definition. The observation reports:

| Observed dependency class | Count |
| --- | ---: |
| ARM64 compiler objects | 201 |
| Project source/header files | 527 |
| Generated headers | 2 |
| System headers | 2,246 |
| ARM64 final link | 1 |
| Local link inputs | 10 |
| System link inputs | 30 |

The CI readback verified object and final-link metadata, source identities, required database/reference translation units, object/final ELF machine `183`, and that observed dependencies were not newer than their objects or final output. The observation JSON is 3,853,796 bytes with SHA-256 `5cd4340b857ea9c7820af5a3432105df93726f1412ed52dde93d8207afbcf0bc`. The new compile-command file is 59,445,763 bytes with SHA-256 `40fcad81c1cfbd064580e06154d75398afb19cae4a36c890523e32f75bd06c6e`.

System header/library identities were observed, but their sources were not copied. Object and link-input bytes were not independently read back outside the CI capture. Unknown original system-input hashes were not compared.

## Source and helper identity

The build retained the archived 2,170-byte source lock with SHA-256 `5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1`, server commit `f35f04d01689f034778e3474b3c820092f51e461`, Eluna commit `58d7652138887783228b9727bd1fa4e08f00342b`, and all seven pinned patches. It used the unchanged 18,216,368-byte source-input archive (`8c820a962947d2b8e2028c434ccedc969127716390f557626444d23ff8e15b99`) and its original receipt, plus the separately pinned 850-byte `ModulesScriptLoader.h` supplement. The original build and module identities remain `cdfd2ea0361f7dbb54b6f820a4cb295eb6b87fdcda32fe5cf4206ac3fe919d31` and `6459b6a1acab2c62c474e4c6ab3eb651daa21f697ccd628e93a38bad298bbdd1`.

| Helper | Bytes | SHA-256 | SQL qualification in this run |
| --- | ---: | --- | --- |
| Newly observed helper | 25,189,160 | `f327179c8467e51afe18d3542fad9186551474c69fae541db3f0461eac5a9542` | None |
| Earlier measured helper | 25,188,512 | `b7d9b72c17f32294915f0a474283c543057ffb7de7b3f93015c2e7e179bfcf25` | Not rerun or transferred |

The first and stabilized helper bytes in this run match each other. They differ from the earlier helper qualified by native SQL run `41076505231`. That earlier build receipt (`82b9c7c852164f303500214e044f07bf5eb389fa2f3f03b9f6cdc962a5bba602`) and SQL receipt (`56288b2ea7046fa256bdd53113701bd59236d5d8403a3a16f32b5fcf0ab53c42`) remain bound to the earlier helper. Source correspondence does not transfer execution qualification or establish bit identity.

The relevant build environment matched the archived requirements before and after compilation. The entire original environment did not match exactly: the receipt records differences in the package inventory, ccache version, and compiler banner, with the compiler alias normalized separately. It does not claim an isolated full-server rebuild or equality with unknown original binary hashes.

## Retention and independent readback

The evidence ZIP (artifact `12996446587`) is 48,838 bytes with SHA-256 `c92de99b1eef25ccb283f2996c3ab795068d2e43b4d0c9b0f8967e0bdcd3cff6`. Its CRC, unique 13-member inventory, all member hashes, and every file identity declared by `environment-receipt.json` were verified from the retained local ZIP. The full qualification JSON is 42,641 bytes with SHA-256 `fdd3d688f44f7b07f0ce26094ee47c7386ef54a2b456508b1279d58176c57bd7`. The status copy is byte-identical. The acquisition receipt and initial helper-build receipt match their qualification pins; the environment objects agree before/after and with the retained environment JSON.

The preparation evidence is a CLI serialization. Re-encoding its parsed object as the producer's sorted, indented JSON plus newline gives the qualification's 5,930-byte preparation pin `6ff44e6198a2c54660c4c85388f6511d5adcb54b3e0ae8d2933871bb61fe0e4f`. Its raw ZIP member has its own separately recorded hash; the two byte identities are not conflated.

GitHub metadata reports the separate source-observation payload as artifact `12996850776`, 206,956,721 bytes, SHA-256 `5400a6efde8daeef086aec7be363b02a2aa0a709bd232de2ca2dbef027c7fc17`. The qualification declares 64 retained payload files excluding its outer receipt. That large payload was not downloaded or independently read back for this compact evidence record. Its metadata is recorded as metadata only; the compact ZIP does not contain the complete dependency graph, compiler-command file, or retained source payload.

`sourceCompanionComplete`, `transitiveIncludeClosureSealed`, SQL execution, replacement of the earlier helper/original three programs, provider activation, Android execution, world entry, playerbots AI, and gameplay qualification remain false. A separate authenticated payload readback and source-companion composition are still required before any source-completeness claim. No database, account, asset conversion, phone activation, or gameplay observation is supplied by this run.
