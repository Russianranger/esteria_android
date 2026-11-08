#!/usr/bin/env bash
set -euo pipefail
umask 077
release_token=${PUBLIC_RELEASE_TOKEN:-}
unset PUBLIC_RELEASE_TOKEN
release_asset() {
    local browser_url=$1 asset_id=$2 destination=$3
    if curl --fail --location --silent --show-error --connect-timeout 20 --max-time 180 --retry 1 \
        "$browser_url" -o "$destination"; then
        return
    fi
    curl --fail --location --silent --show-error --connect-timeout 20 --max-time 180 --retry 3 \
        -H "Authorization: Bearer ${release_token:?read-only release token}" \
        -H 'Accept: application/octet-stream' \
        "https://api.github.com/repos/Russianranger/esteria_android/releases/assets/$asset_id?run=${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}" \
        -o "$destination"
}
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
# Original signed producer c99dbaef634412729742e120d2457d5c7b8bf1a1.
repo_url='https://github.com/Russianranger/esteria_android/releases/download'
if [[ -n "${ESTERIA_DETACHED_CANDIDATE:-}" ]]; then
    ln -- "$ESTERIA_DETACHED_CANDIDATE" "$apk"
else
    curl --fail --location --silent --show-error --retry 3 \
      "$repo_url/non-custom-v0.1.0-non-custom.19/Esteria-Stock-3.3.5a-arm64.apk" -o "$apk"
fi
test "$(stat -c %s "$apk")" = 336899353
echo "c0d251847496c64170bb31d534a925afd1d8e7f92c21687e0e1cbf82c056e6fa  $apk" | sha256sum -c
java -jar "$ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs "$apk" > "$work/signers"
test "$(grep -c '^Signer #[0-9]* certificate SHA-256 digest:' "$work/signers")" = 1
grep -qx 'Signer #1 certificate SHA-256 digest: 5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa' "$work/signers"
previous="$work/input/stock-v18.apk"
release_asset "$repo_url/non-custom-v0.1.0-non-custom.18/Esteria-Stock-3.3.5a-arm64.apk" 723240536 "$previous"
test "$(stat -c %s "$previous")" = 336899353
echo "60a90c58dfc211c53928853dbbebd04929668da69d46d4c0a027c143f6857eb6  $previous" | sha256sum -c
java -jar "$ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs "$previous" > "$work/previous-signers"
diff -u <(grep '^Signer #[0-9]* certificate SHA-256 digest:' "$work/signers") \
        <(grep '^Signer #[0-9]* certificate SHA-256 digest:' "$work/previous-signers")
chmod 0444 "$previous"
unzip -p "$apk" assets/runtime-sources.lock.json > "$work/runtime.json"
diff -u <(jq -cS '.packages["wine-arm64"].archive' runtime/runtime-sources.lock.json) \
        <(jq -cS '.packages["wine-arm64"].archive' "$work/runtime.json")
wine=$(jq -er '.packages["wine-arm64"].archive.url' "$work/runtime.json")
test "$wine" = "$repo_url/deps-wine-arm64-681b2e9-c0e13ed15a69/wine-arm64.tar.gz"
release_asset "$wine" 692421785 "$work/input/wine.tar.gz"
unset release_token
test "$(stat -c %s "$work/input/wine.tar.gz")" = 282628308
echo "c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46  $work/input/wine.tar.gz" | sha256sum -c
chmod 0444 "$work/input/wine.tar.gz"
bash tools/android_stock_shader/compile_driver.sh "$work/dex" "$work/input/driver.jar" database
# This is the exact observer-only DEX independently compiled against the original generated classpath.
test "$(unzip -p "$work/input/driver.jar" classes.dex | sha256sum | cut -d' ' -f1)" = \
    ba88149fdd56be28413f8879c265af7fb2e4a643fef8207cb4aec85c051d2355
cp tools/android_stock_database/{auth_phase,grunt_wine,wine_prefix,wine_windows,world_probe,cold_sql_control}.py tools/{client_auth_contract,prepare_runtime,stock_world_observation}.py "$work/input/"
chmod 0444 "$work/input/"*.py
chmod 755 "$work/input"
chmod 644 "$apk" "$work/input/driver.jar"
redroid_start "$work"
python3 -m tools.android_stock_database.run_database "$out/v18-seed.json" seed18
python3 -m tools.android_stock_database.run_database "$out/owner.json"
