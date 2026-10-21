#!/usr/bin/env bash
# Show or set the macOS tracking-speed slider tick macmouse reproduces.
# Usage: tools/speed.sh            show the ticks and the current setting
#        tools/speed.sh 1..10      save to ~/.config/macmouse/tracking-speed and apply now
set -euo pipefail
CONF=${XDG_CONFIG_HOME:-$HOME/.config}/macmouse/tracking-speed
current=$(grep -v '^\s*#' "$CONF" 2>/dev/null | tr -d ' \n' || true)
current=${current:-10}

if [ $# -eq 0 ]; then
    # Tick -> the value System Settings writes to com.apple.mouse.scaling.
    echo "System Settings > Mouse > Tracking speed (count ticks from Slow):"
    i=0
    for v in 0 0.125 0.5 0.6875 0.875 1 1.5 2 2.5 3; do
        i=$((i + 1))
        printf '  %2d  com.apple.mouse.scaling = %-7s%s\n' "$i" "$v" "$([ "$i" = "$current" ] && echo '  <- current')"
    done
    echo "On the Mac: defaults read -g com.apple.mouse.scaling"
    exit 0
fi

[[ "$1" =~ ^([1-9]|10)$ ]] || { echo "speed must be a tick from 1 (Slow) to 10 (Fast)" >&2; exit 2; }
mkdir -p "$(dirname "$CONF")"
echo "$1" >"$CONF"
if hyprctl plugin list 2>/dev/null | grep -q '^Plugin macmouse '; then
    hyprctl macmouse speed "$1"
else
    echo "saved; applies when macmouse loads"
fi
