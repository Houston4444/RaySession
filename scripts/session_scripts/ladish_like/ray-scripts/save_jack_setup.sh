#!/bin/bash

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0
contents=$(get_current_parameters) || exit 0
echo "$contents" > "$session_jack_file"
exit 0
