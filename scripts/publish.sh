#!/usr/bin/env bash
# Sign the exact successful workflow artifacts; never overwrite release assets.
set -euo pipefail
test "$GITHUB_REPOSITORY" = leoncode-openwrt/packages
test "$GITHUB_REF" = refs/heads/main
test -n "${APK_REPOSITORY_KEY:-}"
root=$(pwd)
key=$(mktemp)
trap 'rm -f "$key"' EXIT
chmod 600 "$key"
printf '%s\n' "$APK_REPOSITORY_KEY" > "$key"
unset APK_REPOSITORY_KEY
openssl pkey -in "$key" -pubout -out "$RUNNER_TEMP/public.pem"
cmp "$RUNNER_TEMP/public.pem" keys/leoncode-packages.pem
sdk_file=$(jq -r '.groups[0].sdk_file' release-lock.json)
sdk_hash=$(jq -r '.groups[0].sdk_sha256' release-lock.json)
curl --fail --location --proto '=https' --proto-redir '=https' \
  "https://downloads.openwrt.org/releases/$RELEASE/targets/x86/64/$sdk_file" -o "$RUNNER_TEMP/$sdk_file"
printf '%s  %s\n' "$sdk_hash" "$RUNNER_TEMP/$sdk_file" | sha256sum -c -
mkdir "$RUNNER_TEMP/sign-sdk"
tar --zstd -xf "$RUNNER_TEMP/$sdk_file" -C "$RUNNER_TEMP/sign-sdk" --strip-components=1
apk="$RUNNER_TEMP/sign-sdk/staging_dir/host/bin/apk"
mkdir -p dist "$RUNNER_TEMP/release-keys"
cp keys/leoncode-packages.pem "$RUNNER_TEMP/release-keys/"
for arch in x86_64 aarch64_cortex-a53 mipsel_24kc; do
  dir="candidates/$arch"
  test "$(find "$dir" -maxdepth 1 -name '*.apk' | wc -l)" -eq 2
  (cd "$dir" && sha256sum -c SHA256SUMS)
  mkdir "$RUNNER_TEMP/build-keys-$arch"
  cp "$dir/build-public-key.pem" "$RUNNER_TEMP/build-keys-$arch/"
  for package in "$dir"/*.apk; do
    "$apk" verify --keys-dir "$RUNNER_TEMP/build-keys-$arch" "$package"
    "$apk" adbsign --allow-untrusted --reset-signatures --sign-key "$key" "$package"
    "$apk" verify --keys-dir "$RUNNER_TEMP/release-keys" "$package"
    "$apk" adbdump --format json "$package" | jq -e --arg arch "$arch" '.info.arch == $arch' >/dev/null
  done
  "$apk" mkndx --keys-dir "$RUNNER_TEMP/release-keys" --sign-key "$key" --output "$dir/packages.adb" "$dir"/*.apk
  "$apk" verify --keys-dir "$RUNNER_TEMP/release-keys" "$dir/packages.adb"
  cp keys/leoncode-packages.pem "$dir/"
  jq '.signature="LeonCode release key" | .published=true' "$dir/verification.json" > "$dir/verification.new"
  mv "$dir/verification.new" "$dir/verification.json"
  "$apk" adbdump --format json "$dir/packages.adb" > "$dir/evidence/index.json"
  (cd "$dir" && sha256sum ./*.apk packages.adb leoncode-packages.pem verification.json > SHA256SUMS)
  tar -czf "dist/LeonCode-openwrt-$RELEASE-$arch.tar.gz" -C candidates "$arch"
done
cp release-lock.json sources/organization-pins.json keys/leoncode-packages.pem keys/LEONCODE_KEY_SHA256 dist/
git archive --format=tar.gz HEAD > dist/LeonCode-build-inputs.tar.gz
(cd dist && sha256sum * > SHA256SUMS)
cat > dist-notes.md <<EOF
LeonCode custom packages for OpenWrt $RELEASE.

All three SDK builds and source regression suites passed. Each architecture
archive includes two signed APKs, its signed index, checksums and evidence.
The build-input archive and release lock identify the exact sources and SDKs.

These are package releases, not firmware images or device upgrade approval.
Hardware boot/runtime behavior has not been validated by this workflow.
Verify the LeonCode public key before use; existing device trust is unchanged.
EOF
# The global workflow concurrency serializes publishers. Existing complete
# releases are immutable; a failed draft is resumed without replacing assets.
if gh release view "$RELEASE_TAG" --json isDraft >/dev/null 2>&1; then
  test "$(gh release view "$RELEASE_TAG" --json isDraft --jq .isDraft)" = true
else
  gh release create "$RELEASE_TAG" --target "$GITHUB_SHA" --draft \
    --title "LeonCode packages for OpenWrt $RELEASE" --notes-file dist-notes.md
fi
for file in dist/*; do
  name=$(basename "$file")
  if gh release view "$RELEASE_TAG" --json assets --jq '.assets[].name' | grep -Fxq "$name"; then
    mkdir -p "$RUNNER_TEMP/existing"
    gh release download "$RELEASE_TAG" --pattern "$name" --dir "$RUNNER_TEMP/existing" --clobber
    cmp "$file" "$RUNNER_TEMP/existing/$name"
  else
    gh release upload "$RELEASE_TAG" "$file"
  fi
done
if [ "$RELEASE" = 25.12.5 ]; then
  # A historical backfill must not replace the current release's Latest badge.
  gh release edit "$RELEASE_TAG" --draft=false --latest=false
else
  gh release edit "$RELEASE_TAG" --draft=false
fi
