#!/bin/bash

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0
contents=$(get_current_parameters) || exit 0
if has_pulse_jack;then
    echo yaplusejack
else
    echo yapapulsejack
fi

echo "$contents" > "$session_jack_file"
exit 0
