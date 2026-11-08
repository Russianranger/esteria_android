#!/usr/bin/env bash
set -euo pipefail
umask 077
test "$(uname -m)" = aarch64
base=$(mktemp -d "${RUNNER_TEMP:?}/stock-donor.XXXXXXXX")
out="$RUNNER_TEMP/esteria-donor-sealed"
test ! -e "$out"
name=esteria-disposable-sql-donor
cleanup() {
    status=$?
    trap - EXIT
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker image rm esteria-donor:verified >/dev/null 2>&1 || true
    [[ "$base" == "$RUNNER_TEMP"/stock-donor.???????? ]]
    if ((status)); then
        # Publish only routine names and source line numbers. Never print native SQL errors, UUIDs,
        # filenames from the fixture, database contents, query text or local account state.
        for phase in setup reopen seal; do
            if sudo test -f "$base/$phase.private"; then
                echo "Reached $phase"
                sudo sed -nE 's/^  File "[^"]*\/(qualification|seal|qualify_packaged_server_auth|qualify_server_installation|observe_stock_world_startup)\.py", line ([0-9]+),.*/\1.py line \2/p' "$base/$phase.private" | tail -12
            fi
        done
    fi
    sudo rm -rf --one-file-system -- "$base"
    if ((status)); then sudo rm -rf --one-file-system -- "$out"; fi
    exit "$status"
}
trap cleanup EXIT
repo=https://github.com/Russianranger/esteria_android/releases
tag=non-custom-v0.1.0-non-custom.18
apk="$base/published.apk"
curl -fsSL --retry 3 "$repo/download/$tag/Esteria-Stock-3.3.5a-arm64.apk" -o "$apk"
test "$(stat -c %s "$apk")" = 336899353
echo "60a90c58dfc211c53928853dbbebd04929668da69d46d4c0a027c143f6857eb6  $apk" | sha256sum -c
python3 - "$base/readback.json" <<'PY'
import json,sys
from tools.stock_sql_donor.qualification import APK,TAG
open(sys.argv[1],'x').write(json.dumps(dict(tag=TAG,assets=[dict(name='Esteria-Stock-3.3.5a-arm64.apk',sha256=APK,bytes=336899353)])))
PY
python3 -m tools.qualify_packaged_server_auth stage --output "$base/package" --apk "$apk" --readback "$base/readback.json"
docker import --platform linux/arm64 "$base/package/server-runtime.tar.gz" esteria-donor:verified >/dev/null
mkdir -m 0700 "$base/work" "$base/evidence"
run=(docker run --rm --name "$name" --init --read-only --network none --pids-limit 512 --memory 5g --cpus 3
    --env PYTHONDONTWRITEBYTECODE=1
    --tmpfs /tmp:rw,nosuid,nodev,size=48m --tmpfs /esteria-data:ro,nosuid,nodev,noexec,size=1m
    --mount "type=bind,src=$GITHUB_WORKSPACE,dst=/qualification,readonly"
    --mount "type=bind,src=$base/package,dst=/package,readonly"
    --mount "type=bind,src=$base/work,dst=/work"
    --mount "type=bind,src=$base/evidence,dst=/evidence"
    --workdir /qualification esteria-donor:verified)
# Diagnostics contain only synthetic state and remain in the private scratch until cleanup.
"${run[@]}" python3 -m tools.qualify_packaged_server_auth run --observe-world >"$base/setup.private" 2>&1
echo 'Fresh four-schema SQL, original auth and bounded world probe finished.'
"${run[@]}" python3 -m tools.stock_sql_donor.qualification >"$base/reopen.private" 2>&1
if docker inspect "$name" >/dev/null 2>&1; then exit 1; fi
echo 'Cold independent native SQL owner closed.'
sudo env PYTHONDONTWRITEBYTECODE=1 python3 -m tools.stock_sql_donor.seal "$base" "$out" >"$base/seal.private" 2>&1
sudo chown -- "$(id -u):$(id -g)" "$out" "$out/qualification.json" "$out/donor.tar.zst.age"
