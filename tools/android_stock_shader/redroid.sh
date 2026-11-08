# Native, network-isolated Android 13 qualification on the disposable hosted ARM64 VM.
redroid_image='redroid/redroid@sha256:c815ac1b1d5bd0a099b74c3e3e0eeea3b32bed8d7ab1f788c20fb74e35891716'
redroid_config='sha256:e4450fd64bbb56954297906128cb9da9a66ff8063c5b9cac5c3e1f95ab229333'
redroid_name=esteria-android-qa

redroid_stop() {
  if docker container inspect "$redroid_name" >/dev/null 2>&1; then
    docker rm -f "$redroid_name" >/dev/null
  fi
  if mountpoint -q "$1/binder"; then sudo umount "$1/binder"; fi
}

redroid_start() {
  local work=$1
  test "$(uname -m)" = aarch64
  if docker container inspect "$redroid_name" >/dev/null 2>&1; then
    echo 'Disposable Android container already exists' >&2
    return 1
  fi
  mkdir -p "$work"/{binder,data,input,import-metadata,mpq}
  docker pull --platform linux/arm64 "$redroid_image" > "$work/android-image-pull.log"
  test "$(docker image inspect -f '{{.Id}}' "$redroid_image")" = "$redroid_config"
  sudo modprobe binder_linux
  sudo mount -t binder binder "$work/binder"
  sudo python3 - "$work/binder" <<'PY'
import array, fcntl, os, stat, sys
from pathlib import Path
base = Path(sys.argv[1])
with (base / 'binder-control').open('r+b', buffering=0) as control:
    for name in ('binder', 'hwbinder', 'vndbinder'):
        path = base / name
        if not path.exists():
            data = bytearray(264)
            data[:len(name)] = name.encode('ascii')
            fcntl.ioctl(control, 0xc1086201, data)
        with path.open('r+b', buffering=0) as dev:
            assert stat.S_ISCHR(os.fstat(dev.fileno()).st_mode)
            version = array.array('i', [0])
            fcntl.ioctl(dev, 0xc0046209, version)
            assert version[0] == 8
        path.chmod(0o666)
PY
  local boot_started
  boot_started=$(date -u '+%Y-%m-%d %H:%M:%S')
  docker run -d --name "$redroid_name" --pull=never --platform linux/arm64 \
    --privileged --network none --cgroupns=private \
    --device "$work/binder/binder:/dev/binder" \
    --device "$work/binder/hwbinder:/dev/hwbinder" \
    --device "$work/binder/vndbinder:/dev/vndbinder" \
    --mount "type=bind,source=$work/data,target=/data" \
    --mount "type=bind,source=$work/input,target=/esteria-qa/input,readonly" \
    --mount "type=bind,source=$work/import-metadata,target=/esteria-qa/import-metadata,readonly" \
    --mount "type=bind,source=$work/mpq,target=/esteria-qa/mpq,readonly" \
    "$redroid_image" androidboot.use_memfd=1 androidboot.redroid_gpu_mode=guest \
    androidboot.redroid_width=1920 androidboot.redroid_height=1080 androidboot.redroid_dpi=320 >/dev/null
  test "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$redroid_name")" = none
  local deadline=$((SECONDS+300))
  until test "$(docker exec "$redroid_name" /system/bin/getprop sys.boot_completed 2>/dev/null || true)" = 1; do
    if ! test "$(docker inspect -f '{{.State.Running}}' "$redroid_name")" = true || (( SECONDS >= deadline )); then
      echo 'Android failed before completed boot' >&2
      docker inspect -f 'container={{.State.Status}} exit={{.State.ExitCode}}' "$redroid_name"
      docker exec "$redroid_name" /system/bin/sh -c 'for s in zygote servicemanager surfaceflinger; do echo "$s=$(/system/bin/getprop init.svc.$s)"; done' || true
      docker logs "$redroid_name" > "$work/android-boot-private.log" 2>&1 || true
      # Android is still in early init; neither the APK nor the stock data was opened.
      head -c 6000 "$work/android-boot-private.log"
      echo "kernel=$(uname -r) pages=$(getconf PAGESIZE)"
      sudo dmesg --since "$boot_started" | grep -Ei 'init:|redroid|binder|surfaceflinger|/dev/kmsg|avc: denied|segfault' | tail -65 || true
      return 1
    fi
    sleep 2
  done
  test "$(docker exec "$redroid_name" /system/bin/getprop ro.build.version.sdk)" = 33
  test "$(docker exec "$redroid_name" /system/bin/getprop ro.product.cpu.abi)" = arm64-v8a
  docker exec "$redroid_name" /system/bin/sh -c 'test -x /system/bin/app_process64 && /system/bin/cmd package path android | /system/bin/grep -q "^package:"'
  local android_pid
  android_pid=$(docker inspect -f '{{.State.Pid}}' "$redroid_name")
  sudo nsenter -t "$android_pid" -n -- python3 -c 'import socket; assert set(x[1] for x in socket.if_nameindex())=={"lo"}'
}
