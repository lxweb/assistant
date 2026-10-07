#!/usr/bin/env bash
set -euo pipefail

UNIT_SRC="$(cd "$(dirname "$0")" && pwd)/assistant.service"
UNIT_DST="$HOME/.config/systemd/user/assistant.service"

mkdir -p "$HOME/.config/systemd/user"
cp "$UNIT_SRC" "$UNIT_DST"
systemctl --user daemon-reload
systemctl --user enable assistant.service
echo "Instalado. Arrancar con: systemctl --user start assistant"
echo "Logs: journalctl --user -u assistant -f"
