#!/usr/bin/env bash
# Builds only the explicitly selected 25.12.6 packages in an isolated Linux SDK.
# Never installs on a device or publishes. Source archives are checked by OpenWrt.
set -euo pipefail
[[ $# == 2 ]] || { echo 'usage: build-prepared.sh ARCH ABSOLUTE_SDK_DIRECTORY' >&2; exit 2; }
task_arch=$1
task_sdk=$(realpath "$2")
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$task_repo/scripts/sdk-provenance.py" check-sdk "$task_arch" "$task_sdk"
task_group=$(jq -ce --arg arch "$task_arch" '.groups[] | select(.arch == $arch)' "$task_repo/build-matrix-25.12.6.json")
[[ $(uname -s) == Linux && -x "$task_sdk/scripts/feeds" ]] || exit 2
[[ ! -e "$task_sdk/.custom-prepared" ]] || { echo 'Use a fresh SDK, not a previously prepared one.' >&2; exit 2; }
mkdir -p "$task_sdk/custom-distfiles" "$task_sdk/dl" "$task_sdk/package/custom"
cp "$task_repo"/sources/*.tar.* "$task_sdk/custom-distfiles/"
cp "$task_repo"/sources/*.tar.* "$task_sdk/dl/"
while IFS=$'\t' read -r task_name task_recipe; do
    [[ ! -e "$task_sdk/package/custom/$task_name" ]]
    cp -a "$task_repo/packages/$task_recipe" "$task_sdk/package/custom/$task_name"
done < <(jq -r '.recipes | to_entries[] | [.key,.value] | @tsv' <<<"$task_group")

cd "$task_sdk"
# The official SDK pins the complete feed commit; only change the HTTPS mirror.
sed -i 's#https://git.openwrt.org/openwrt/openwrt.git#https://github.com/openwrt/openwrt.git#' feeds.conf.default
./scripts/feeds update base
./scripts/feeds install -p base libjson-c libubox uci ubus libnl-tiny libpcap
cat > .config <<'CONFIG'
CONFIG_ALL=n
CONFIG_ALL_KMODS=n
CONFIG_ALL_NONSHARED=n
CONFIG_AUTOREMOVE=n
CONFIG_SIGNED_PACKAGES=y
CONFIG_IPV6=y
CONFIG_PACKAGE_odhcpd=n
CONFIG_PACKAGE_odhcpd-ipv6only=n
CONFIG_PACKAGE_ustp=n
CONFIG_PACKAGE_usteer=n
CONFIG
while IFS= read -r task_package; do
    printf 'CONFIG_PACKAGE_%s=y\n' "$task_package" >> .config
done < <(jq -r '.packages[]' <<<"$task_group")
make defconfig
while IFS= read -r task_package; do
    grep -Eq "^CONFIG_PACKAGE_${task_package}=(y|m)$" .config || {
        echo "Requested package not selected after defconfig: $task_package" >&2
        exit 1
    }
done < <(jq -r '.packages[]' <<<"$task_group")
printf '%s\n' "$task_group" > .custom-prepared
python3 "$task_repo/scripts/sdk-provenance.py" begin "$task_arch" "$task_sdk"
while IFS= read -r task_name; do
    make "package/$task_name/compile" -j1 V=s
done < <(jq -r '.recipes | keys[]' <<<"$task_group")
python3 "$task_repo/scripts/sdk-provenance.py" finish "$task_arch" "$task_sdk"
