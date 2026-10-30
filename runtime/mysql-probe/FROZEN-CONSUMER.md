# Frozen MySQL fixture consumer

The original `fetch_android_mysql_fixture.py` keeps its strict check of all21
producer source files. Current Java owner changes therefore require an explicit
historical recipe to recover the already qualified fixture. The original guard,
provider, Android receipts and source artifacts are unchanged.

`fetch_android_mysql_fixture_frozen.py` fixes that recipe to
`817cbc229f4dcc24beb169ecc72838fab4d1df32`. It binds the original6,228-byte
selection (`5268fa26eb1e2165f0cf5ff9f90686792abb4af6b9af48288d75932009bf853d`),
the positive4fd Android fixture evidence and the actual817 full-source consumer
receipt. `input_selection()` validates only this metadata and returns the
original pin; it neither compares current Java bytes with historical bytes nor
claims that a checkout has been verified.

`inspect(checkout)` and `selection(checkout)` additionally read every canonical
Git blob and working file at the exact817 commit. They reject dirty or untracked
files, including ignored files, hidden index flags, links and executable-mode
drift. Only the exact declared LF-to-CRLF checkout of `gradlew.bat` is permitted;
the receipt retains both identities. Python source requires exact blob bytes.
No historical Python module is imported or executed during selection.

After this verification, acquisition invokes only the fixed historical script:

```sh
python3 -B tools/fetch_android_mysql_fixture_frozen.py \
  --frozen-consumer-source /absolute/clean-817-checkout \
  --output /absolute/new-output-outside-checkout
```

Use a separate `actions/checkout` step with the exact817 revision in CI. The
child uses `-B -s -E`, excludes Python environment injection, retains supported
network/token/proxy/CA settings and writes no output inside its checkout. The
entire checkout is verified again afterward. Existing outputs are refused.

The historical `acquisition.json` remains byte-for-byte untouched. A separate
`frozen-consumer-readback.json` records current caller file identities, the
frozen recipe, original runtime producer, full input/source readback and explicit
qualification boundaries. Historical Android Java service evidence applies only
to its recorded producer; recovering its bytes does not qualify current owner
changes, ARM64 execution, four-schema coordination or gameplay.
