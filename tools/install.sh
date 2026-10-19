#!/usr/bin/env bash
# Install macmouse for the current user: device config + autostart hook, then load now.
# Usage: tools/install.sh [hyprland-device-name ...]   (see `hyprctl devices`)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CONF_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/macmouse
HYPR=${XDG_CONFIG_HOME:-$HOME/.config}/hypr
MARK="# macmouse autostart"

mkdir -p "$CONF_DIR"
if [ $# -gt 0 ]; then
    printf '%s\n' "$@" >"$CONF_DIR/devices"
elif [ ! -s "$CONF_DIR/devices" ]; then
    echo "Name the mouse to transform. Mice Hyprland sees:" >&2
    hyprctl -j devices | python3 -c 'import json,sys; [print("  " + m["name"]) for m in json.load(sys.stdin)["mice"]]' >&2
    echo "Re-run: tools/install.sh <name>" >&2
    exit 2
fi
echo "devices: $(tr '\n' ' ' <"$CONF_DIR/devices")"

if [ -f "$HYPR/autostart.lua" ] || [ -f "$HYPR/hyprland.lua" ]; then
    TARGET=$HYPR/autostart.lua
    [ -f "$TARGET" ] || TARGET=$HYPR/hyprland.lua
    LINE="hl.on(\"hyprland.start\", function() hl.exec_cmd(\"$REPO/tools/load.sh\") end) -- macmouse autostart"
    grep -q 'macmouse autostart' "$TARGET" || { cp "$TARGET" "$TARGET.bak.macmouse"; printf '\n%s\n' "$LINE" >>"$TARGET"; }
else
    TARGET=$HYPR/hyprland.conf
    LINE="exec-once = $REPO/tools/load.sh $MARK"
    grep -q 'macmouse autostart' "$TARGET" || { cp "$TARGET" "$TARGET.bak.macmouse"; printf '\n%s\n' "$LINE" >>"$TARGET"; }
fi
echo "autostart: $TARGET"

"$REPO/tools/load.sh" || { tail -20 "${XDG_STATE_HOME:-$HOME/.local/state}/macmouse/load.log"; exit 1; }
hyprctl macmouse status
echo "Installed. Verify with: make verify"
