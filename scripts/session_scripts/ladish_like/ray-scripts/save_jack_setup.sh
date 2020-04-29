#!/bin/bash

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0
contents=$(get_current_parameters) || exit 0
echo "$contents" > "$RAY_SESSION_PATH/jack_parameters"
exit 0
