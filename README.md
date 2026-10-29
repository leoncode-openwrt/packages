# LeonCode OpenWrt packages

Reproducible custom package builds using official OpenWrt release SDKs.
This is an independent packaging repository. Sources remain reviewable upstream forks:

| Source | Branch | Packages and architectures |
| --- | --- | --- |
| [ustp](https://github.com/leoncode-openwrt/ustp) | `main` | ustp / x86_64, aarch64_cortex-a53, mipsel_24kc |
| [usteer](https://github.com/leoncode-openwrt/usteer) | `main` | usteer / aarch64_cortex-a53, mipsel_24kc |
| [odhcpd](https://github.com/leoncode-openwrt/odhcpd) | `main` | odhcpd-ipv6only / x86_64 |

## Automatic release builds

Actions checks the official OpenWrt version inventory twice daily. Final releases
from 25.12.6 onward are eligible; release candidates and moving snapshots are
excluded. Missing releases are retried. Source pins never follow a moving branch.
Future incompatible SDKs fail validation instead of publishing partial packages.

Each release verifies the signed OpenWrt SDK checksum lists, runs regression tests,
builds all six packages, checks metadata, ELF architecture and dependencies, then
signs packages and one aggregate index per architecture. All targets must pass.
[GitHub Releases](https://github.com/leoncode-openwrt/packages/releases) contains
architecture archives, source and SDK manifests, checksums and validation evidence.
Actions artifacts are build candidates, not published or hardware-tested packages.

Each archive contains `packages.adb` and a public verification key. Builds are tied
to the exact OpenWrt release and APK architecture. A release build is not a snapshot
build, even when the processor architecture matches. The new LeonCode signing key
is independent of the historical JxnLexn feed. Verify `keys/` before trusting it.
No workflow installs packages, changes device configuration or flashes firmware.
Hardware boot and runtime acceptance remain separate from build verification.

## Using the APK feed

[GitHub Pages](https://leoncode-openwrt.github.io/packages/) publishes the signed
feed after each successful release publication. Scheduled and manual runs also
retry deployment when no new OpenWrt release needs building.

| APK architecture | OpenWrt 25.12.6 feed |
| --- | --- |
| x86_64 | https://leoncode-openwrt.github.io/packages/25.12.6/x86_64/packages.adb |
| aarch64_cortex-a53 | https://leoncode-openwrt.github.io/packages/25.12.6/aarch64_cortex-a53/packages.adb |
| mipsel_24kc | https://leoncode-openwrt.github.io/packages/25.12.6/mipsel_24kc/packages.adb |

Use only the feed matching the device's exact OpenWrt release and APK architecture
(`. /etc/openwrt_release; echo "$DISTRIB_RELEASE"; cat /etc/apk/arch`). These feeds
do not support 25.12.5 or snapshots. Keep the official OpenWrt feeds enabled for
dependencies. Adding a feed does not itself install packages or ensure that an
Attended Sysupgrade server can include them.

For a deliberately approved device setup:

1. Download [leoncode-packages.pem](https://leoncode-openwrt.github.io/packages/leoncode-packages.pem).
   Verify its DER SHA-256 against the value below (for example on an administrator
   computer using `openssl pkey -pubin -in leoncode-packages.pem -outform DER | openssl dgst -sha256`).
   Then copy it to `/etc/apk/keys/leoncode-packages.pem` on the device.
2. Add the matching index URL above as a single line in
   `/etc/apk/repositories.d/customfeeds.list`, preserving existing entries.
3. Run `apk update`, then inspect `apk policy ustp usteer` or
   `apk policy ustp odhcpd-ipv6only`. Review the selected versions before any
   separate package installation. Never bypass signature verification.

Public key DER SHA-256:

```text
ef2cc07584ad56d57d494a924d7636937b0cbf8e65d3b2e81e7be667285a7e6c
```

Each deployment reconstructs all published versions from immutable GitHub release
assets, checks archive hashes and package signatures, and selects the highest
numeric recipe revision per OpenWrt version. Revision-qualified package paths
(`/<release>/<arch>/rN/`) keep cached older indices usable; the stable signed index
references the selected revision. Previously published paths cannot disappear,
and APK bytes at an existing path cannot change. Do not delete release assets.

Pages publication requires the repository signing secret only to sign the stable
indices. Package files are copied unchanged. The deployment is atomic; all feeds
are staged together. After deployment, CI downloads and checks every published
file and uses the pinned OpenWrt APK tool to update and fetch from all active feeds
in isolated temporary roots. No packages are installed and no devices are contacted.

## Traceable source maintenance

`sources/prepared-pins.json` preserves the reviewed archive/patch provenance.
`sources/organization-pins.json` links the resulting source trees to exact commits
in the LeonCode forks. Original authorship and licenses are preserved. The initial
inputs originate from the earlier JxnLexn work; publication branding is LeonCode.

All USTP builds use one recipe and the same source commit, including DSA reception
and shutdown fixes, regardless of device role. odhcpd retains the deployed stable
DNS relay backport rather than a newer unrelated fork tip. Each fork has an English
`LEONCODE.md` explaining its changes and remaining upstream-review questions.
Build pins must be ancestors of the corresponding repository's `main` branch.
The older role-specific USTP builds remain in release `openwrt-25.12.6-r1`.

Source updates require a reviewed commit/patch pin and tests. Changed package
bytes require a new package revision. Release assets are never overwritten.
Signing is isolated from compilation; pull requests receive no signing secrets.
SDKs and Actions are pinned, and OpenWrt checksum signatures are verified against
the committed build-system key. The private signing key is the repository secret
`APK_REPOSITORY_KEY`; it is never committed or included in artifacts.

GitHub may delay scheduled workflows and disables public-repository schedules
after 60 days without repository activity. Check Actions health periodically;
manual dispatch is available. No artificial keepalive commits are created.

The former fixed-version publication/source-tip workflows are retired here.
Existing JxnLexn repositories, device feeds and trust stores remain unchanged.
