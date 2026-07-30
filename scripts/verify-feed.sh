#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <apk-tool> <feed-dir> <expected-architecture>" >&2
  exit 2
fi

apk_tool=$1
feed_dir=$2
expected_arch=$3

shopt -s nullglob
packages=("$feed_dir"/*.apk)
if (( ${#packages[@]} == 0 )); then
  echo "No APK packages found in $feed_dir" >&2
  exit 1
fi

test -s "$feed_dir/packages.adb"
test -s "$feed_dir/jxnlexn-openwrt-packages.pem"

keys_dir=$(mktemp -d)
trap 'rm -rf "$keys_dir"' EXIT
cp "$feed_dir/jxnlexn-openwrt-packages.pem" "$keys_dir/"

"$apk_tool" verify --keys-dir "$keys_dir" "$feed_dir/packages.adb"
"$apk_tool" adbdump --format json "$feed_dir/packages.adb" > "$feed_dir/index.json"

for package in "${packages[@]}"; do
  "$apk_tool" verify --keys-dir "$keys_dir" "$package"
  metadata=$("$apk_tool" adbdump --format json "$package")
  printf '%s\n' "$metadata" > "$package.json"
  printf '%s\n' "$metadata" | jq -e \
    --arg arch "$expected_arch" \
    '.info.arch == $arch' >/dev/null
done

(
  cd "$feed_dir"
  sha256sum ./*.apk packages.adb jxnlexn-openwrt-packages.pem > SHA256SUMS
)
