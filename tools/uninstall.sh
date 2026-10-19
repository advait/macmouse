#!/usr/bin/env bash
# Remove the autostart hook and unload macmouse. Device config and logs are kept.
set -uo pipefail
HYPR=${XDG_CONFIG_HOME:-$HOME/.config}/hypr
for f in "$HYPR/autostart.lua" "$HYPR/hyprland.lua" "$HYPR/hyprland.conf"; do
    [ -f "$f" ] && grep -q 'macmouse autostart' "$f" && sed -i '/macmouse autostart/d' "$f" && echo "removed hook from $f"
done
for p in "${XDG_DATA_HOME:-$HOME/.local/share}"/macmouse/*.so; do
    [ -f "$p" ] && hyprctl plugin unload "$p" >/dev/null 2>&1 && echo "unloaded $p"
done
rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/macmouse"
echo "macmouse uninstalled; stock libinput acceleration is active."
