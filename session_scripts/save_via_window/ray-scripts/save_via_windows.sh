#!/bin/sh

for executable in xdotool; do
    if ! command -v "$executable" >/dev/null; then
        exit
    fi
done

[ -n "$WAYLAND_DISPLAY" ] && exit

start_win=$(xdotool getactivewindow)
focus_changed=false

for client_id in $(ray_control list_clients no_save_level); do
    executable_line=$(ray_control client "$client_id" get_proxy_properties | grep ^executable:)
    executable=$(basename "${executable_line#*:}")

    [ -n "$executable" ] || continue

    wins=$(xdotool search --class "$executable")

    for windowid in $wins; do
        if [ "$(xdotool getwindowname "$windowid")" != "*" ]; then
            focus_changed=true
            xdotool windowactivate "$windowid"
            xdotool key ctrl+s
            break
        fi
    done
done

if $focus_changed; then
    xdotool windowactivate "$start_win"
fi

exit 0
