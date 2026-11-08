#!/usr/bin/env bash
set -euo pipefail
work=$(realpath -m "$1")
out=$(realpath -m "$2")
root=$(cd "$(dirname "$0")/../.." && pwd)
sdk=${ANDROID_HOME:?Android SDK required}
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
javac --release 17 -implicit:none -cp "$cp" -sourcepath "$src" -d "$classes" \
    "$root/tools/android_stock_shader/ConfirmShader.java"
jar cf "$work/observer.jar" -C "$classes" .
if find "$classes" -type f ! -name 'ConfirmShader*.class' | grep -q .; then
    echo "Unexpected non-observer class in QA driver" >&2
    exit 1
fi
"$sdk/build-tools/35.0.0/d8" --min-api 33 --lib "$android" --output "$out" "$work/observer.jar"
