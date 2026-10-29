# LeonCode OpenWrt packages

Reproducible custom package builds using official OpenWrt release SDKs.
This is an independent packaging repository. Sources remain reviewable upstream forks:

| Source | Branch | Packages and architectures |
| --- | --- | --- |
| [ustp](https://github.com/leoncode-openwrt/ustp) | `leoncode/router` | ustp / x86_64 |
| [ustp](https://github.com/leoncode-openwrt/ustp) | `leoncode/ap` | ustp / aarch64_cortex-a53, mipsel_24kc |
| [usteer](https://github.com/leoncode-openwrt/usteer) | `leoncode/stable` | usteer / aarch64_cortex-a53, mipsel_24kc |
| [odhcpd](https://github.com/leoncode-openwrt/odhcpd) | `leoncode/stable` | odhcpd-ipv6only / x86_64 |

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

## Traceable source maintenance

`sources/prepared-pins.json` preserves the reviewed archive/patch provenance.
`sources/organization-pins.json` links the resulting source trees to exact commits
in the LeonCode forks. Original authorship and licenses are preserved. The initial
inputs originate from the earlier JxnLexn work; publication branding is LeonCode.

The router USTP branch excludes AP-specific DSA/shutdown changes. odhcpd retains
the deployed stable DNS relay backport rather than a newer unrelated fork tip.
Each fork has an English `LEONCODE.md` explaining its changes and maintenance line.

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
