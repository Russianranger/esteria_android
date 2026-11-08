#!/usr/bin/env bash
# Runs only inside this QA job's transient PID/mount/network namespaces.
set -euo pipefail
stage=$1
checkout=$2
qa_uid=$3
qa_gid=$4
guest=$stage/guest
[[ "$(id -u)" == 0 && "$qa_uid" -gt 0 && "$guest" == "$RUNNER_TEMP"/stock-grunt-????????/guest ]]
mount --make-rprivate /
ip link set lo up
[[ "$(ip -o link show | wc -l)" -eq 1 ]]
tar --extract --gzip --numeric-owner --file "$stage/packaged-server/server-runtime.tar.gz" --directory "$guest"
mkdir -p "$guest"/{proc,dev,package,work,evidence,qualification,esteria-data,tmp}
chmod 755 "$guest"
mount --bind "$guest" "$guest"
mount -o remount,bind,ro,nosuid,nodev "$guest"
mount -t proc -o nosuid,nodev,noexec proc "$guest/proc"
mount -t tmpfs -o mode=755,nosuid tmpfs "$guest/dev"
for device in null zero random urandom; do
  touch "$guest/dev/$device"
  mount --bind "/dev/$device" "$guest/dev/$device"
done
mount -t tmpfs -o size=32m,mode=1777,nosuid,nodev tmpfs "$guest/tmp"
for mapping in "packaged-server:package" "disposable-server:work" "server-evidence:evidence"; do
  mount --bind "$stage/${mapping%%:*}" "$guest/${mapping##*:}"
done
mount -o remount,bind,ro,nosuid,nodev "$guest/package"
mount --bind "$checkout" "$guest/qualification"
mount -o remount,bind,ro,nosuid,nodev "$guest/qualification"
# chroot and namespace creation are setup actions. The entire retained Python
# parent, mysqld and unmodified authserver run as the same unprivileged UID.
exec setpriv --no-new-privs chroot --userspec="$qa_uid:$qa_gid" --groups="$qa_gid" "$guest" \
  /usr/bin/env -i HOME=/work PATH=/usr/sbin:/usr/bin:/sbin:/bin PYTHONDONTWRITEBYTECODE=1 LANG=C LC_ALL=C \
  /bin/sh -c 'cd /qualification && exec /usr/bin/python3 -m tools.qualify_packaged_server_auth run'
