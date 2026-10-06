#!/usr/bin/env bash
# Install for the current user from this source folder. Needs NO pip.
# usage: ./install.sh ['<Ctrl>x']   (default Ctrl+X opens/closes the pill; note it overrides Cut)
set -euo pipefail
KEY="${1:-<Ctrl>x}"
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/nothing-tasks"
BIN="$HOME/.local/bin"
mkdir -p "$DEST" "$BIN" "$HOME/.local/share/applications" "$HOME/.config/autostart"

rm -rf "$DEST/nothing_tasks"
cp -r "$HERE/nothing_tasks" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +

for pair in "nothing-tasks:nothing_tasks.cli" "nothing-tasks-mcp:nothing_tasks.mcp_server"; do
  name=${pair%%:*}; mod=${pair##*:}
  printf '#!/bin/sh\nexec python3 -c '"'"'import sys; sys.path.insert(0, "%s"); from %s import main; sys.exit(main())'"'"' "$@"\n' \
    "$DEST" "$mod" > "$BIN/$name"
  chmod 755 "$BIN/$name"
done
install -m 755 "$HERE/bin/nothing-tasks-ctl" "$BIN/nothing-tasks-ctl"
install -m 644 "$HERE/packaging/nothing-tasks.desktop" "$HOME/.local/share/applications/"
sed "s|^Exec=nothing-tasks|Exec=$BIN/nothing-tasks|" "$HERE/packaging/nothing-tasks-autostart.desktop" \
  > "$HOME/.config/autostart/nothing-tasks.desktop"

export PATH="$BIN:$PATH"
if nothing-tasks install-shortcut "$KEY"; then :; else
  echo "Shortcut not set. Bind '$BIN/nothing-tasks-ctl toggle' in Settings > Keyboard > Custom."; fi
echo
nothing-tasks doctor || true
echo
echo "Installed to $DEST. Try:  $BIN/nothing-tasks toggle"
case ":$PATH:" in *":$BIN:"*) ;; esac
