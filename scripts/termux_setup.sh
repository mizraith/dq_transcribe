#!/data/data/com.termux/files/usr/bin/bash
# Termux environment setup for dq_transcribe.
#
# Installs the system packages the project needs and creates a Python virtual
# environment in the repo. Safe to re-run.
#
# Usage (from the repo root, inside Termux):
#     bash scripts/termux_setup.sh
#
# Note: written without access to a device. Report any error text so it can be fixed.

set -euo pipefail

SYSTEM_PACKAGES="python git clang cmake make ffmpeg"
VIRTUAL_ENV_DIRECTORY=".venv"

echo "Updating package lists..."
pkg update -y
pkg upgrade -y

echo "Installing system packages: ${SYSTEM_PACKAGES}"
# shellcheck disable=SC2086  # word splitting of the package list is intended
pkg install -y ${SYSTEM_PACKAGES}

echo "Requesting shared-storage access (tap Allow if prompted)..."
termux-setup-storage || true

echo "Creating virtual environment in ${VIRTUAL_ENV_DIRECTORY}..."
python -m venv "${VIRTUAL_ENV_DIRECTORY}"

echo
echo "Done. Next steps:"
echo "  1. Start the app:   PYTHONPATH=src python -m dq_transcribe"
echo "  2. In Chrome on this tablet, open http://localhost:8000"
echo "  3. Tap Record, allow the microphone, and speak for a few seconds."
