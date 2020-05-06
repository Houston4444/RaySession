#!/bin/bash

cd "$(dirname "`readlink -f "$(realpath "$0")"`")"
source shared.sh || exit 0
contents=$(get_current_parameters) || exit 0
echo "$contents" > "$session_jack_file"
exit 0
