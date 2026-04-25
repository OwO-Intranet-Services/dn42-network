#!/usr/bin/env bash
set -euo pipefail

# Regenerate .github/ssh_known_hosts from host_vars/*/ssh_host_keys.yaml
# Run this after changing any node's SSH host keys.

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${REPO_ROOT}/.github/ssh_known_hosts"

: > "$OUT"

for keyfile in "${REPO_ROOT}"/host_vars/*/ssh_host_keys.yaml; do
  node="$(basename "$(dirname "$keyfile")")"
  host="${node}.node.svc.moe"
  pub="$(grep '^ssh_host_ed25519_public_key:' "$keyfile" | sed 's/^ssh_host_ed25519_public_key: *"\(.*\)"/\1/')"
  if [ -n "$pub" ]; then
    key_type="$(echo "$pub" | awk '{print $1}')"
    key_data="$(echo "$pub" | awk '{print $2}')"
    echo "${host} ${key_type} ${key_data}" >> "$OUT"
  fi
done

echo "Wrote $(wc -l < "$OUT" | tr -d ' ') entries to $OUT"
