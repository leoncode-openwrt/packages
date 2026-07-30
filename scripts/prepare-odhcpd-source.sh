#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <recipe> <source-ref>" >&2
  exit 2
fi

recipe=$1
source_ref=$2

if [[ ! "$source_ref" =~ ^[0-9a-f]{40}$ ]]; then
  echo "source-ref must be a full 40-character Git commit" >&2
  exit 1
fi

api_url="https://api.github.com/repos/JxnLexn/openwrt-odhcpd/commits/${source_ref}"
auth_header=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  auth_header=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
fi

commit_json=$(curl --fail --silent --show-error --location \
  -H 'Accept: application/vnd.github+json' \
  "${auth_header[@]}" \
  "$api_url")
resolved_ref=$(jq -r '.sha' <<<"$commit_json")
if [[ "$resolved_ref" != "$source_ref" ]]; then
  echo "Commit does not resolve exactly in JxnLexn/openwrt-odhcpd" >&2
  exit 1
fi

source_date=$(jq -r '.commit.committer.date[0:10]' <<<"$commit_json")
short_ref=${source_ref:0:8}

if [[ ! "$source_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "GitHub returned an invalid commit date" >&2
  exit 1
fi

perl -pi -e \
  "s/^PKG_SOURCE_DATE:=.*/PKG_SOURCE_DATE:=${source_date}/; \
   s/^PKG_SOURCE_VERSION:=.*/PKG_SOURCE_VERSION:=${source_ref}/" \
  "$recipe"

echo "Building odhcpd source ${short_ref} from ${source_date}"
