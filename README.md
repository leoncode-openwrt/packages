# JxnLexn OpenWrt APK feed

This repository builds and publishes signed custom packages for OpenWrt. One
feed can contain any number of packages; package recipes live below
`packages/`, and every supported OpenWrt package architecture receives its own
signed `packages.adb` index.

## Current packages

| Package source | OpenWrt release | Architecture | Produced packages |
| --- | --- | --- | --- |
| [`JxnLexn/openwrt-odhcpd`](https://github.com/JxnLexn/openwrt-odhcpd) | 25.12.5 | `x86_64` | `odhcpd-ipv6only` |

The published feed is available at:

```text
https://jxnlexn.github.io/openwrt-packages/25.12.5/x86_64/packages.adb
```

## Add the feed to OpenWrt

Download the repository public key from:

```text
https://jxnlexn.github.io/openwrt-packages/jxnlexn-openwrt-packages.pem
```

Its SHA-256 fingerprint over the public key in DER form is:

```text
985e75a3222225c67087a8fdef4b3ddcc5d2ffa7aaa0275093d3783d23e75eea
```

Verify this fingerprint against a trusted copy of this README, then install
the key as:

```text
/etc/apk/keys/jxnlexn-openwrt-packages.pem
```

Add the architecture-specific index URL to:

```text
/etc/apk/repositories.d/customfeeds.list
```

For the current x86_64 router, that line is:

```text
https://jxnlexn.github.io/openwrt-packages/25.12.5/x86_64/packages.adb
```

Then refresh the package indexes with `apk update`. LuCI uses the same APK
configuration and will show packages from the custom feed after the refresh.
Installing the public key or feed is an infrastructure change; inspect the
key fingerprint and repository contents first.

## Build and publication model

- Pull requests build packages without signing or publishing them.
- Pushes to branches other than `main` build packages without signing or
  publishing them.
- A daily updater resolves and verifies the latest odhcpd commit. It commits a
  changed pin to `main` and explicitly starts the normal build and publication
  path.
- Manual updater runs and `odhcpd-updated` repository-dispatch events can
  trigger the same pin-update path immediately.
- Manual build runs rebuild the package set pinned in the repository.
- Only a successful build on the default branch can access the protected
  `pages` environment, sign the aggregate index, and deploy GitHub Pages.
- The private EC P-256 key is stored only as the GitHub Actions secret
  `APK_REPOSITORY_KEY`. It is never committed or uploaded as an artifact.
- Each SDK archive is pinned by filename and SHA-256.
- Existing packages are rebuilt together before publication, so the resulting
  feed always contains one coherent index rather than mutually overwriting
  per-package deployments.

The source pin is maintained in
[`packages/odhcpd/Makefile`](packages/odhcpd/Makefile). A dispatch from the
source repository may pass a commit as `client_payload.source_ref`; the
updater verifies that the full commit belongs to `JxnLexn/openwrt-odhcpd`
before committing it. This keeps every published build reproducible from the
central repository history. Only the IPv6-only package is currently defined
because that is the deployed and verified router variant. The full variant can
be added later as a separate, deliberate recipe selection.

## Add another package

1. Add an OpenWrt package recipe below `packages/<name>/`.
2. Add the package selection and collection pattern to the workflow.
3. Add the target architecture to the workflow matrix if it is not already
   present.
4. Build all packages for that architecture and let the workflow generate one
   aggregate `packages.adb`.

One device therefore needs only the single JxnLexn feed for its OpenWrt
release and architecture, regardless of how many source forks supply packages.
