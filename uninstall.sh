#!/usr/bin/env bash
set -u
BIN="$HOME/.local/bin"
"$BIN/nothing-tasks" remove-shortcut 2>/dev/null
"$BIN/nothing-tasks" quit 2>/dev/null
rm -rf "$HOME/.local/share/nothing-tasks"
rm -f "$BIN/nothing-tasks" "$BIN/nothing-tasks-mcp" "$BIN/nothing-tasks-ctl" \
      "$HOME/.local/share/applications/nothing-tasks.desktop" "$HOME/.config/autostart/nothing-tasks.desktop"
echo "Removed. Your tasks stay in your Obsidian vault; settings remain in ~/.config/nothing-tasks."
