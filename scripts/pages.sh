#!/usr/bin/env bash
set -euo pipefail
test "$GITHUB_REPOSITORY" = leoncode-openwrt/packages
test "$GITHUB_REF" = refs/heads/main
# Fixed verification tool, independent of the release being published.
sdk=openwrt-sdk-25.12.6-x86-64_gcc-14.3.0_musl.Linux-x86_64.tar.zst
curl --fail --location --proto '=https' --proto-redir '=https' \
  "https://downloads.openwrt.org/releases/25.12.6/targets/x86/64/$sdk" -o "$RUNNER_TEMP/$sdk"
printf '%s  %s\n' 1864152619092e781fa36a401960c8e9ae42d6a364c44ee5f0b197ca5f3c0fcc "$RUNNER_TEMP/$sdk" | sha256sum -c -
mkdir "$RUNNER_TEMP/pages-sdk"
tar --zstd -xf "$RUNNER_TEMP/$sdk" -C "$RUNNER_TEMP/pages-sdk" --strip-components=1
apk="$RUNNER_TEMP/pages-sdk/staging_dir/host/bin/apk"
printf 'PAGES_APK=%s\n' "$apk" >> "$GITHUB_ENV"
key=$(mktemp)
trap 'rm -f "$key"' EXIT
chmod 600 "$key"
printf '%s\n' "$APK_REPOSITORY_KEY" > "$key"
unset APK_REPOSITORY_KEY
openssl pkey -in "$key" -pubout -out "$RUNNER_TEMP/pages-public.pem"
cmp "$RUNNER_TEMP/pages-public.pem" keys/leoncode-packages.pem
python3 scripts/pages.py prepare --apk "$apk" --key "$key"
tar -cf "$RUNNER_TEMP/artifact.tar" -C _site .
