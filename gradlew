#!/bin/sh
# Minimal launcher for the official Apache-2.0 Gradle wrapper.
set -eu
APP_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -n "${JAVA_HOME:-}" ]; then
  JAVA_CMD="$JAVA_HOME/bin/java"
else
  JAVA_CMD=java
fi
# JAVA_OPTS and GRADLE_OPTS deliberately retain the standard wrapper word splitting.
# shellcheck disable=SC2086
exec "$JAVA_CMD" ${JAVA_OPTS:-} ${GRADLE_OPTS:-} -classpath "$APP_HOME/gradle/wrapper/gradle-wrapper.jar" org.gradle.wrapper.GradleWrapperMain "$@"
