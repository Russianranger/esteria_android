#!/usr/bin/env bash
set -euo pipefail
work=$1
mkdir -p "$work/classes" "$work/generated/io/github/russianranger/esteria"
python3 - "$work" <<'PY'
from pathlib import Path
import re, sys
fields = {'DEBUG': 'boolean'}
for script in Path('app').glob('*.gradle'):
    for kind, name in re.findall(r"buildConfigField\s+'(String|boolean|int|long)',\s*'([A-Z0-9_]+)'", script.read_text()):
        fields[name] = kind
stub = Path(sys.argv[1]) / 'generated/io/github/russianranger/esteria/BuildConfig.java'
stub.write_text('package io.github.russianranger.esteria; public final class BuildConfig {\n'
                + ''.join(f'public static {kind} {name};\n' for name, kind in fields.items()) + '}\n')
PY
platform="$ANDROID_HOME/platforms/android-35/android.jar"
javac --release 17 -implicit:none -cp "$platform" -sourcepath "app/src/main/java:core/src/main/java:$work/generated" \
    -d "$work/classes" tools/retained_database/SignedDatabaseUpdate.java
if find "$work/classes" -type f ! -name 'SignedDatabaseUpdate*.class' | grep -q .; then
    echo "Unexpected product class in observer DEX" >&2
    exit 1
fi
jar cf "$work/classes.jar" -C "$work/classes" .
"$ANDROID_HOME/build-tools/35.0.0/d8" --min-api 33 --lib "$platform" --output "$work/observer.jar" "$work/classes.jar"
