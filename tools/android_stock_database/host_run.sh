#!/usr/bin/env bash
set -euo pipefail
umask 077
source tools/android_stock_shader/redroid.sh
work=$(mktemp -d "${RUNNER_TEMP:?}/esteria-native-db.XXXXXXXX")
out="$RUNNER_TEMP/android-stock-db-evidence"
mkdir -p "$out" "$work/input"
close() {
    status=$?
    trap - EXIT
    redroid_stop "$work" || status=1
    if ! docker inspect "$redroid_name" >/dev/null 2>&1 && ! mountpoint -q "$work/binder"; then
        sudo rm -rf --one-file-system -- "$work"
    fi
    exit "$status"
}
trap close EXIT
apk="$work/input/stock.apk"
repo_url='https://github.com/Russianranger/esteria_android/releases/download'
curl --fail --location --silent --show-error --retry 3 \
  "$repo_url/non-custom-v0.1.0-non-custom.16/Esteria-Stock-3.3.5a-arm64.apk" -o "$apk"
test "$(stat -c %s "$apk")" = 336887065
echo "de9d108a725aeb7a8eea1041bd1a72eb7a5acde811595cf71c886f6937f74ab4  $apk" | sha256sum -c
java -jar "$ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs "$apk" > "$work/signers"
test "$(grep -c '^Signer #[0-9]* certificate SHA-256 digest:' "$work/signers")" = 1
grep -qx 'Signer #1 certificate SHA-256 digest: 5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa' "$work/signers"
unzip -p "$apk" assets/runtime-sources.lock.json > "$work/runtime.json"
diff -u <(jq -cS '.packages["wine-arm64"].archive' runtime/runtime-sources.lock.json) \
        <(jq -cS '.packages["wine-arm64"].archive' "$work/runtime.json")
wine=$(jq -er '.packages["wine-arm64"].archive.url' "$work/runtime.json")
test "$wine" = "$repo_url/deps-wine-arm64-681b2e9-c0e13ed15a69/wine-arm64.tar.gz"
curl --fail --location --silent --show-error --retry 3 "$wine" -o "$work/input/wine.tar.gz"
test "$(stat -c %s "$work/input/wine.tar.gz")" = 282628308
echo "c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46  $work/input/wine.tar.gz" | sha256sum -c
chmod 0444 "$work/input/wine.tar.gz"
bash tools/android_stock_shader/compile_driver.sh "$work/dex" "$work/input/driver.jar" database
cp tools/android_stock_database/{auth_phase,grunt_wine,wine_prefix,world_probe}.py tools/{client_auth_contract,prepare_runtime,stock_world_observation}.py "$work/input/"
chmod 0444 "$work/input/"*.py
chmod 755 "$work/input"
chmod 644 "$apk" "$work/input/driver.jar"
redroid_start "$work"
python3 tools/android_stock_shader/package_lifecycle.py --container "$redroid_name" --report "$out/package.json"
python3 -m tools.android_stock_database.run_database "$out/owner.json"
