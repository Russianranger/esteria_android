#!/usr/bin/env bash
set -euo pipefail
work=$(realpath -m "$1")
out=$(realpath -m "$2")
root=$(cd "$(dirname "$0")/../.." && pwd)
sdk=${ANDROID_HOME:?Android SDK required}
case "${3:-shader}" in
    shader) driver="$root/tools/android_stock_shader/ConfirmShader.java"; name=ConfirmShader ;;
    database) driver="$root/tools/android_stock_database/ConfirmDatabase.java"; name=ConfirmDatabase ;;
    *) echo "Unknown observer" >&2; exit 2 ;;
esac
classes="$work/observer-classes"
mkdir -p "$work" "$(dirname "$out")"
mkdir "$classes"
android="$sdk/platforms/android-35/android.jar"
cp="$android"
src="$root/app/src/main/java:$root/core/src/main/java"
if [[ -n "${ESTERIA_APP_CLASS_PATH:-}" ]]; then
    cp="$cp:$ESTERIA_APP_CLASS_PATH"
else
    (cd "$root" && ./gradlew --no-daemon :app:generateDebugBuildConfig)
    generated="$root/app/build/generated/source/buildConfig/debug"
    test -f "$generated/io/github/russianranger/esteria/BuildConfig.java"
    src="$src:$generated"
fi
extra=("$root/tools/android_stock_database/ConfirmPrefixTrace.java" "$root/tools/android_stock_database/ConfirmLegacy.java")
javac --release 17 -implicit:none -cp "$cp" -sourcepath "$src" -d "$classes" \
    "$driver" "${extra[@]}"
jar cf "$work/observer.jar" -C "$classes" .
if find "$classes" -type f ! -name "${name}*.class" ! -name 'ConfirmPrefixTrace*.class' ! -name 'ConfirmLegacy*.class' | grep -q .; then
    echo "Unexpected non-observer class in QA driver" >&2
    exit 1
fi
"$sdk/build-tools/35.0.0/d8" --min-api 33 --lib "$android" --output "$out" "$work/observer.jar"
# D8 emits synthetic classes for lambdas. Inspect class_defs, not arbitrary descriptor strings.
python3 - "$out" <<'PY'
import re,struct,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as files:
    assert [n for n in files.namelist() if n.endswith('.dex')]==['classes.dex']
    data=files.read('classes.dex')
u32=lambda n:struct.unpack_from('<I',data,n)[0]
owners=[]
for i in range(u32(96)):
    offset=u32(u32(60)+4*u32(u32(68)+4*u32(u32(100)+32*i)))
    while data[offset]&128:offset+=1
    offset+=1
    name=data[offset:data.index(0,offset)].decode('ascii')
    match=re.fullmatch(r'Lio/github/russianranger/esteria/runtime/(ConfirmDatabase|ConfirmLegacy|ConfirmPrefixTrace)(?:\$[A-Za-z0-9$-]+)?;',name)
    if not match:raise ValueError('unexpected DEX class definition')
    owners.append(match[1])
assert set(owners)=={'ConfirmDatabase','ConfirmLegacy','ConfirmPrefixTrace'}
print('External DEX contains three QA observers and their nested/synthetic classes only:',len(owners),'definitions.')
PY
