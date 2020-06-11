#!/bin/bash

source shared.sh || exit 0
contents=$(get_current_parameters)

if $RAY_FAIL_IF_JACK_DIFF && [ -f "$session_jack_file" ];then
    wanted_parameters=$(cat "$session_jack_file") || exit 3
    make_diff_parameters
    [ -n "$diff_parameters" ] && exit 29
fi

echo "$contents" > "$session_jack_file"
exit 0
