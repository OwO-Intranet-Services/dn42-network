#!/usr/bin/env bash
set -euo pipefail

test -n "${ANSIBLE_VAULT_PASSWORD:-}" || {
  echo "::error::ANSIBLE_VAULT_PASSWORD secret is required."
  exit 1
}

mkdir -p .secrets
chmod 700 .secrets
printf '%s' "$ANSIBLE_VAULT_PASSWORD" > .secrets/vault_pass.txt
chmod 600 .secrets/vault_pass.txt
