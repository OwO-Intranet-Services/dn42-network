#!/usr/bin/env bash
set -euo pipefail

GALAXY_REQUIREMENTS=""
PIP_PACKAGES=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --galaxy)
      GALAXY_REQUIREMENTS="$2"
      shift 2
      ;;
    *)
      PIP_PACKAGES+=("$1")
      shift
      ;;
  esac
done

if ! python3 -m venv .ci-venv; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    PYTHON_VENV_PKG="python$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')-venv"
    sudo apt-get update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$PYTHON_VENV_PKG"
    python3 -m venv .ci-venv
  else
    echo "Failed to create a virtualenv and sudo is unavailable to install the matching -venv package."
    exit 1
  fi
fi

echo "$PWD/.ci-venv/bin" >> "$GITHUB_PATH"
. .ci-venv/bin/activate
python -m pip install --upgrade pip

if [[ ${#PIP_PACKAGES[@]} -gt 0 ]]; then
  python -m pip install "${PIP_PACKAGES[@]}"
fi

if [[ -n "$GALAXY_REQUIREMENTS" ]]; then
  ansible-galaxy collection install -r "$GALAXY_REQUIREMENTS"
fi
