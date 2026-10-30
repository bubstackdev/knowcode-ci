#!/bin/sh
# Installs a pinned KnowCode release into DIR and prints the binary's path.
#
#   install.sh VERSION DIR
#
# Downloads the release archive for this machine from github.com/bubstackdev/know-code, checks it against the
# release's SHA-256 file, and checks its build provenance attestation (the release workflow attests every archive):
# the attestation is read from GitHub's API, which serves a public repository's without a token, and checked with
# `gh attestation verify --bundle`, which then needs none either. Either check failing stops the job. Needs curl,
# tar, python3 and gh; KNOWCODE_SKIP_ATTESTATION=1 skips the attestation check, and says so.
set -eu

version=$1
dir=$2
repo=bubstackdev/know-code
case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) target=x86_64-unknown-linux-gnu ;;
    Linux-aarch64 | Linux-arm64) target=aarch64-unknown-linux-gnu ;;
    Darwin-arm64) target=aarch64-apple-darwin ;;
    *) echo "knowcode-ci: no KnowCode release for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
archive="knowcode-$target.tar.gz"
url="https://github.com/$repo/releases/download/v$version"
mkdir -p "$dir"
cd "$dir"
curl -fsSL --retry 3 -o "$archive" "$url/$archive"
curl -fsSL --retry 3 -o "$archive.sha256" "$url/$archive.sha256"
want=$(cut -d' ' -f1 < "$archive.sha256")
if command -v sha256sum >/dev/null; then got=$(sha256sum "$archive" | cut -d' ' -f1); else got=$(shasum -a 256 "$archive" | cut -d' ' -f1); fi
if [ "$want" != "$got" ]; then
    echo "knowcode-ci: $archive's SHA-256 is $got, the release says $want" >&2
    exit 1
fi
if [ "${KNOWCODE_SKIP_ATTESTATION:-0}" = 1 ]; then
    echo "knowcode-ci: attestation check skipped (KNOWCODE_SKIP_ATTESTATION=1)" >&2
else
    auth=""
    [ -n "${GH_TOKEN:-}" ] && auth="Authorization: Bearer $GH_TOKEN"
    curl -fsSL --retry 3 ${auth:+-H "$auth"} -o attestations.json "https://api.github.com/repos/$repo/attestations/sha256:$got"
    python3 -c 'import json, sys; [print(json.dumps(a["bundle"])) for a in json.load(open(sys.argv[1]))["attestations"]]' \
        attestations.json > attestations.jsonl
    gh attestation verify "$archive" --bundle attestations.jsonl --repo "$repo" >&2
fi
tar -xzf "$archive"
bin=$(find "$dir" -type f -name knowcode | head -n 1)
[ -x "$bin" ] || { echo "knowcode-ci: no knowcode binary in $archive" >&2; exit 1; }
"$bin" --version >&2
echo "$bin"
