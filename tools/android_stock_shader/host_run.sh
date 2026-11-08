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
work=$(mktemp -d "${RUNNER_TEMP:?}/esteria-stock-shaders.XXXXXX")
reports="$RUNNER_TEMP/android-stock-shader-evidence"
mkdir -p "$reports" "$work/input" "$work/mpq"
phase=inputs
fuse_pid=
start=$SECONDS
cleanup() {
  local result=$?
  trap - EXIT
  set +e
  redroid_stop "$work" || result=1
  if mountpoint -q "$work/mpq"; then sudo umount "$work/mpq" || result=1; fi
  if [[ -n "$fuse_pid" ]]; then
    if ! timeout 10 tail --pid="$fuse_pid" -f /dev/null; then sudo kill "$fuse_pid" || true; fi
    wait "$fuse_pid" || result=1
  fi
  denied=0
  if [[ -e "$work/guard.log" ]]; then denied=$(grep -c '^Denied unauthenticated shader read' "$work/guard.log" || true); fi
  jq -n --arg phase "$phase" --arg kernel "$(uname -r)" --arg arch "$(uname -m)" \
    --arg sha 'c0d251847496c64170bb31d534a925afd1d8e7f92c21687e0e1cbf82c056e6fa' \
    --argjson exit "$result" --argjson denied "$denied" --argjson elapsed "$((SECONDS-start))" \
    '{phase:$phase,kernel:$kernel,arch:$arch,apkSha256:$sha,exitCode:$exit,guardDenied:$denied,elapsedSeconds:$elapsed,physicalThor:false}' \
    > "$reports/host.json"
  # This host-created, private mktemp leaf is our only writable store, including stock material.
  if ! mountpoint -q "$work/mpq" && ! mountpoint -q "$work/binder" && ! docker inspect "$redroid_name" >/dev/null 2>&1; then
    sudo rm -rf --one-file-system -- "$work"
  fi
  exit "$result"
}
trap cleanup EXIT
apk="$work/input/stock.apk"
repo_url='https://github.com/Russianranger/esteria_android/releases/download'
ln -- "${ESTERIA_DETACHED_CANDIDATE:?}" "$apk"
test "$(stat -c %s "$apk")" = 336899353
echo "c0d251847496c64170bb31d534a925afd1d8e7f92c21687e0e1cbf82c056e6fa  $apk" | sha256sum -c
java -jar "$ANDROID_HOME/build-tools/35.0.0/lib/apksigner.jar" verify --verbose --print-certs "$apk" > "$work/signers"
test "$(grep -c '^Signer #[0-9]* certificate SHA-256 digest:' "$work/signers")" = 1
grep -qx 'Signer #1 certificate SHA-256 digest: 5e6921a036142cf2da217ddd17a3f7bb734706268e4ee913e2037da898b4d9fa' "$work/signers"
unzip -p "$apk" assets/runtime-sources.lock.json > "$work/runtime.json"
diff -u <(jq -cS '.packages["wine-arm64"].archive' runtime/runtime-sources.lock.json) \
        <(jq -cS '.packages["wine-arm64"].archive' "$work/runtime.json")
wine=$(jq -er '.packages["wine-arm64"].archive.url' "$work/runtime.json")
test "$wine" = "$repo_url/deps-wine-arm64-681b2e9-c0e13ed15a69/wine-arm64.tar.gz"
release_asset "$wine" 692421785 "$work/input/wine.tar.gz"
unset release_token
test "$(stat -c %s "$work/input/wine.tar.gz")" = 282628308
echo "c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46  $work/input/wine.tar.gz" | sha256sum -c
phase=compile-observer
bash tools/android_stock_shader/compile_driver.sh "$work/dex" "$work/input/driver.jar"
chmod 0755 "$work/input"
chmod 0444 "$work/input/"{stock.apk,wine.tar.gz,driver.jar}
phase=source-windows
/usr/bin/python3 -B tools/android_stock_shader/prepare_ranges.py --output "$work/corpus"
cp "$work/corpus/source-metrics.json" "$reports/source.json"
mv "$work/corpus/import-metadata" "$work/import-metadata"
phase=guard
sudo modprobe fuse || test -c /dev/fuse
truncate -s 24 "$work/range-counters"
sudo /usr/bin/python3 -B tools/android_stock_shader/serve_ranges.py "$work/corpus/source" "$work/mpq" --stats "$work/range-counters" > "$work/guard.log" 2>&1 &
fuse_pid=$!
deadline=$((SECONDS+45))
until mountpoint -q "$work/mpq"; do
  kill -0 "$fuse_pid"
  ((SECONDS < deadline))
  sleep 1
done
sudo /usr/bin/python3 - "$work/mpq" <<'PY'
import errno, os, pwd, sys
# Hold a directory capability through the host's private 0700 parent, then observe the FUSE view under an ordinary UID.
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
nobody = pwd.getpwnam('nobody')
os.setgroups([])
os.setresgid(nobody.pw_gid, nobody.pw_gid, nobody.pw_gid)
os.setresuid(nobody.pw_uid, nobody.pw_uid, nobody.pw_uid)
asset = os.open('Data/common.MPQ', os.O_RDONLY, dir_fd=fd)
assert os.pread(asset,4,0) == b'MPQ\x1a'
try:
    os.pread(asset,2,266239)
except OSError as error:
    assert error.errno == errno.EIO
else:
    raise RuntimeError('kernel FUSE returned bytes across an unverified interval')
PY
test "$(grep -c '^Denied unauthenticated shader read' "$work/guard.log")" = 1
phase=boot-offline-android
redroid_start "$work"
phase=installed-apk-lifecycle
python3 tools/android_stock_shader/package_lifecycle.py --container "$redroid_name" --report "$reports/package.json"
phase=android-shader-owner
extra=()
if [[ ${ESTERIA_EXERCISE_NAMED_REPAIR:-false} == true ]]; then
  extra+=(--repair-report "$reports/repair.json")
fi
python3 tools/android_stock_shader/run_owner.py --container "$redroid_name" --report "$reports/owner.json" --range-counters "$work/range-counters" "${extra[@]}"
phase=owner-cleanup
python3 tools/android_stock_shader/package_lifecycle.py --container "$redroid_name" --report "$reports/package.json" --check-reaped
test "$(grep -c '^Denied unauthenticated shader read' "$work/guard.log")" = 1
phase=complete
