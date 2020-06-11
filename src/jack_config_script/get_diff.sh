#!/bin/bash

source shared.sh || exit 0

ray_operation=load

# read current and session parameters, and diff between them
current_parameters=$(get_current_parameters for_load)

if [ -n "$1" ];then
    # keep parameters of a (multi-lines) argument
    wanted_parameters="$1"
elif [ -f "$session_jack_file" ];then
    # keep parameters from session file
    wanted_parameters=$(cat "$session_jack_file")
else
    exit 0
fi

make_diff_parameters
echo "$diff_parameters"
exit 0
