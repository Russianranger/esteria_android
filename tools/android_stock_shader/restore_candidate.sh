#!/usr/bin/env bash
set -euo pipefail
umask 077
package=${1:?original CI artifact}
packet=${2:?detached packet directory}
work=${3:?private extraction directory}
test "$(stat -c %s "$package")" = 336905382
echo "8f9ca2bfb42fe091d1764b5c6350be01e63a3d76f628afd5cffcd537eed23267  $package" | sha256sum -c
echo "b32757e5a3eb9b65ef5d3d815e28b1329a9f210f232ca0068d4c90ac87d32d20  $packet/signature-recipe.json" | sha256sum -c
unzip -p "$package" app/build/outputs/apk/release/app-release-unsigned.apk > "$work/unsigned.apk"
python3 tools/export_apk_signature.py apply --unsigned "$work/unsigned.apk" \
    --recipe "$packet/signature-recipe.json" --output "$work/signed.apk"
echo "c0d251847496c64170bb31d534a925afd1d8e7f92c21687e0e1cbf82c056e6fa  $work/signed.apk" | sha256sum -c
rm -- "$work/unsigned.apk"
