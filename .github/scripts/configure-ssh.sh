#!/usr/bin/env bash
set -euo pipefail

test -n "${ANSIBLE_SSH_PRIVATE_KEY:-}" || {
  echo "::error::ANSIBLE_SSH_PRIVATE_KEY secret is required."
  exit 1
}

mkdir -p ~/.ssh
chmod 700 ~/.ssh
printf '%s\n' "$ANSIBLE_SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
chmod 600 ~/.ssh/id_ed25519
cp .github/ssh_known_hosts ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
