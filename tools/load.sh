#!/usr/bin/env bash
# Load macmouse into the running Hyprland session (run at every Hyprland start).
#
# A build is loaded only after it passed tools/nested_check.py for this exact
# Hyprland ABI and this repository's build/verification inputs. After a
# Hyprland update or a source change the plugin is rebuilt and re-validated
# first. Any failure leaves stock behavior and raises a desktop notification.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/macmouse
LIB=${XDG_DATA_HOME:-$HOME/.local/share}/macmouse
CONF=${XDG_CONFIG_HOME:-$HOME/.config}/macmouse/devices
mkdir -p "$STATE" "$LIB"
exec >>"$STATE/load.log" 2>&1
echo "== $(date -Is) load"

fail() {
    echo "FAIL: $*"
    notify-send -u critical "macmouse" "macOS pointer transform NOT loaded: $*" || true
    exit 1
}

for _ in $(seq 100); do timeout 5 hyprctl version -j >/dev/null 2>&1 && break; sleep 0.1; done
ABI=$(hyprctl version -j | python3 -c 'import json,sys; print(json.load(sys.stdin)["abiHash"])') || fail "Hyprland not reachable"

DEVICES=$(grep -v '^\s*#' "$CONF" 2>/dev/null | tr -s ' \n' ',' | sed 's/^,//; s/,$//')
[ -n "$DEVICES" ] || fail "no devices in $CONF (see README)"

if ! hyprctl plugin list | grep -q '^Plugin macmouse '; then
    # Validation key: everything that defines the build and its acceptance check.
    KEY=$(cd "$REPO" && cat Makefile src/macmouse.cpp src/pointer_profile.hpp profiles/table-segments.hex.csv \
          tools/probe_plugin.cpp tools/expect.py tools/nested_check.py \
          tests/isolated-hyprland.conf tests/apple-pointer-vectors.csv.gz | sha256sum | cut -c1-16)
    GOOD="$LIB/macmouse-${ABI:0:12}-$KEY.so"
    if [ ! -f "$GOOD" ]; then
        echo "no validated build for $ABI / $KEY: rebuilding"
        rm -f "$REPO/build/macmouse.so" "$REPO/build/probe_plugin.so"
        make -C "$REPO" plugin || fail "build failed for Hyprland $ABI"
        timeout 180 python3 "$REPO/tools/nested_check.py" >"$STATE/nested-${ABI:0:12}-$KEY.json" ||
            fail "nested isolation check failed (see $STATE)"
        cp "$REPO/build/macmouse.so" "$GOOD.tmp" && mv "$GOOD.tmp" "$GOOD"
        sha256sum "$GOOD" >"$GOOD.sha256"
    fi
    # Load only the exact ELF that passed validation.
    if ! sha256sum --quiet -c "$GOOD.sha256"; then
        rm -f "$GOOD" "$GOOD.sha256"
        fail "validated build changed on disk"
    fi
    out=$(hyprctl plugin load "$GOOD")
    [ "$out" = ok ] || fail "plugin load: $out"
    echo "loaded $GOOD"
fi

hyprctl macmouse devices "$DEVICES" >/dev/null
status=$(hyprctl macmouse status)
echo "$status"
case "$status" in *'"selftest":true'*) ;; *) fail "self-test failed" ;; esac
