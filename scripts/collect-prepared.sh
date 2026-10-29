#!/usr/bin/env bash
# Verify and collect SDK candidates. The SDK build key is NOT the production key.
set -euo pipefail
[[ $# == 3 ]] || { echo 'usage: collect-prepared.sh ARCH SDK OUTPUT_ROOT' >&2; exit 2; }
[[ $(id -u) != 0 ]] || { echo 'Run collection as the unprivileged SDK build user (APK usermode).' >&2; exit 2; }
task_arch=$1
task_sdk=$(realpath "$2")
task_output=$(realpath -m "$3")
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$task_repo/scripts/sdk-provenance.py" verify "$task_arch" "$task_sdk"
task_group=$(jq -ce --arg arch "$task_arch" '.groups[] | select(.arch == $arch)' "$task_repo/build-matrix-25.12.6.json")
task_apk_arch=$(jq -r .apk_arch <<<"$task_group")
task_apk="$task_sdk/staging_dir/host/bin/apk"
[[ -x "$task_apk" && -s "$task_sdk/public-key.pem" && -s "$task_sdk/private-key.pem" ]]
[[ ! -e "$task_output/$task_arch" ]] || { echo 'Refusing to overwrite existing candidates.' >&2; exit 2; }
mkdir -p "$task_output"
task_temp=$(mktemp -d "$task_sdk/candidate-check.XXXXXX")
trap 'rm -rf "$task_temp"' EXIT
mkdir -p "$task_temp/keys" "$task_temp/build-keys" "$task_temp/all-built" "$task_temp/candidate/evidence"
cp "$task_sdk/public-key.pem" "$task_temp/keys/build-public-key.pem"
cp "$task_sdk/public-key.pem" "$task_temp/build-keys/build-public-key.pem"
cp "$task_sdk/public-key.pem" "$task_temp/candidate/build-public-key.pem"

# The SDK's mkpkg emits unsigned APKs, including bundled toolchain packages.
# Their provenance is the checked SDK archive or this build from pinned sources.
# Sign COPIES in the isolated build context, then require strict verification.
# --allow-untrusted is used only by the signing operation, never by validation,
# extraction, dependency simulation or installation.
# No target device or network is used during verification.
while IFS= read -r -d '' task_package; do
    task_basename=$(basename "$task_package")
    if [[ -e "$task_temp/all-built/$task_basename" ]]; then
        cmp "$task_package" "$task_temp/all-built/$task_basename"
    else
        cp "$task_package" "$task_temp/all-built/$task_basename"
    fi
done < <(find "$task_sdk/bin" -type f -name '*.apk' -print0)
for task_package in "$task_temp"/all-built/*.apk; do
    "$task_apk" adbsign --allow-untrusted --reset-signatures \
        --sign-key "$task_sdk/private-key.pem" "$task_package"
    "$task_apk" verify --keys-dir "$task_temp/build-keys" "$task_package"
done
"$task_apk" mkndx --keys-dir "$task_temp/keys" \
    --sign-key "$task_sdk/private-key.pem" --output "$task_temp/all-built/packages.adb" \
    "$task_temp"/all-built/*.apk
"$task_apk" verify --keys-dir "$task_temp/keys" "$task_temp/all-built/packages.adb"

task_specs=()
while IFS=$'\t' read -r task_name task_version task_binary; do
    task_package="$task_temp/all-built/$task_name-$task_version.apk"
    [[ -s "$task_package" ]]
    "$task_apk" verify --keys-dir "$task_temp/build-keys" "$task_package"
    task_metadata="$task_temp/candidate/evidence/$task_name.metadata.json"
    "$task_apk" adbdump --format json "$task_package" > "$task_metadata"
    jq -e --arg name "$task_name" --arg version "$task_version" --arg arch "$task_apk_arch" \
        '.info.name == $name and .info.version == $version and .info.arch == $arch' \
        "$task_metadata" >/dev/null
    mkdir "$task_temp/extract-$task_name"
    "$task_apk" extract --keys-dir "$task_temp/keys" --no-chown \
        --destination "$task_temp/extract-$task_name" "$task_package"
    [[ -x "$task_temp/extract-$task_name/$task_binary" ]]
    [[ -z $(find "$task_temp/extract-$task_name" -name '*.ko' -o -iname '*private*key*') ]]
    case "$task_name" in
        ustp) test -x "$task_temp/extract-$task_name/etc/init.d/ustpd" ;;
        usteer) test -x "$task_temp/extract-$task_name/etc/init.d/usteer"
                test -f "$task_temp/extract-$task_name/etc/config/usteer" ;;
        odhcpd-ipv6only) test -x "$task_temp/extract-$task_name/etc/init.d/odhcpd"
                       test -x "$task_temp/extract-$task_name/usr/sbin/odhcpd-update" ;;
    esac
    task_elf="$task_temp/candidate/evidence/$task_name.elf.txt"
    readelf -h -l -d "$task_temp/extract-$task_name/$task_binary" > "$task_elf"
    case "$task_arch" in
        x86_64) grep -q 'Machine:.*Advanced Micro Devices X86-64' "$task_elf" ;;
        aarch64_cortex-a53) grep -q 'Machine:.*AArch64' "$task_elf" ;;
        mipsel_24kc) grep -q 'Machine:.*MIPS' "$task_elf"
                     grep -q 'Data:.*little endian' "$task_elf" ;;
        *) exit 2 ;;
    esac
    grep -q '/lib/ld-musl-' "$task_elf"
    (cd "$task_temp/extract-$task_name" && find . -type f -exec sha256sum '{}' + | sort) \
        > "$task_temp/candidate/evidence/$task_name.payload-sha256.txt"
    cp "$task_package" "$task_temp/candidate/"
    task_specs+=("$task_name=$task_version")
done < <(jq -r '.artifacts[] | [.name,.version,.binary] | @tsv' <<<"$task_group")

mkdir "$task_temp/root"
# --simulate does not initialize a missing database, even with --initdb.
# Initialize an EMPTY disposable database first; no packages or scripts run.
"$task_apk" --root "$task_temp/root" --usermode --initdb --arch "$task_apk_arch" \
    --keys-dir "$task_temp/keys" --repositories-file /dev/null --no-scripts \
    --no-network add
"$task_apk" --root "$task_temp/root" --usermode --initdb --arch "$task_apk_arch" \
    --keys-dir "$task_temp/keys" --repositories-file /dev/null \
    --repository "$task_temp/all-built/packages.adb" --simulate --no-scripts --no-network \
    add "${task_specs[@]}" 2>&1 | tee "$task_temp/candidate/evidence/dependency-simulation.txt"

"$task_apk" mkndx --keys-dir "$task_temp/keys" --sign-key "$task_sdk/private-key.pem" \
    --output "$task_temp/candidate/packages.adb" "$task_temp"/candidate/*.apk
"$task_apk" verify --keys-dir "$task_temp/build-keys" "$task_temp/candidate/packages.adb"
"$task_apk" adbdump --format json "$task_temp/candidate/packages.adb" \
    > "$task_temp/candidate/evidence/index.json"
cp "$task_sdk/.config" "$task_temp/candidate/evidence/sdk.config"
cp "$task_sdk/feeds.conf.default" "$task_temp/candidate/evidence/feeds.conf"
cp "$task_sdk/.custom-build-receipt.json" "$task_temp/candidate/evidence/build-receipt.json"
jq '.inputs.source_manifest' "$task_sdk/.custom-build-receipt.json" > "$task_temp/candidate/evidence/prepared-pins.json"
jq '.inputs.group' "$task_sdk/.custom-build-receipt.json" > "$task_temp/candidate/evidence/build-group.json"
jq -n --arg arch "$task_arch" \
    '{release:"25.12.6",architecture:$arch,signature:"isolated SDK build key; not the production feed key",signature_verified:true,metadata_verified:true,elf_verified:true,dependency_simulation:"passed against packages built in this SDK; no install scripts executed",device_tested:false,published:false}' \
    > "$task_temp/candidate/verification.json"
(cd "$task_temp/candidate" && sha256sum ./*.apk packages.adb build-public-key.pem verification.json > SHA256SUMS)
cp -a "$task_temp/candidate" "$task_output/$task_arch"
printf 'Verified candidates: %s\n' "$task_output/$task_arch"
