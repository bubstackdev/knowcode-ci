#!/bin/sh
# Installs the GitHub CLI into DIR (DIR/bin/gh), for the KnowCode release's attestation check on runners without it.
#
#   install-gh.sh VERSION DIR
#
# Only the versions pinned below, each checked against its SHA-256 as recorded here (from that release's checksums
# file), so a changed download stops the job.
set -eu

version=$1
dir=$2
case "$version-$(uname -m)" in
    2.102.0-x86_64) arch=amd64 sum=bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386 ;;
    2.102.0-aarch64 | 2.102.0-arm64) arch=arm64 sum=7862c86c72f43df3a2d93ddde6f473285b4e2af61b494849846827e513ef6484 ;;
    *) echo "knowcode-ci: no pinned GitHub CLI $version for $(uname -m)" >&2; exit 1 ;;
esac
name="gh_${version}_linux_$arch"
mkdir -p "$dir"
curl -fsSL --retry 3 -o "$dir/$name.tar.gz" "https://github.com/cli/cli/releases/download/v$version/$name.tar.gz"
got=$(sha256sum "$dir/$name.tar.gz" | cut -d' ' -f1)
if [ "$got" != "$sum" ]; then
    echo "knowcode-ci: $name.tar.gz's SHA-256 is $got, expected $sum" >&2
    exit 1
fi
tar -xzf "$dir/$name.tar.gz" -C "$dir" --strip-components=1
"$dir/bin/gh" --version >&2
