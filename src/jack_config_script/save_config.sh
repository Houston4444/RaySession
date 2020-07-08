#!/bin/bash

source shared.sh || exit 0
contents=$(get_current_parameters)
echo "$contents" > "$session_jack_file"
exit 0
