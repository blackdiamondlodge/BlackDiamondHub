#!/bin/sh
# Install a site's extracted apps (sites/<site>/apps.txt, hashed wheel URLs).
# GitHub's release CDN occasionally returns a short error body with a 200, which
# pip reports as a hash mismatch and does not retry, so retry the whole install.
set -eu
site="${1:?usage: install_apps.sh <site>}"
req="sites/${site}/apps.txt"
grep -qvE '^[[:space:]]*(#|$)' "$req" || exit 0
n=1
until pip install --no-cache-dir --require-hashes --no-deps -r "$req"; do
    [ "$n" -ge 4 ] && exit 1
    echo "apps install failed (attempt $n), retrying in $((n * 10))s" >&2
    sleep $((n * 10))
    n=$((n + 1))
done