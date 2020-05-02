#!/bin/bash

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0
[ -f "$backup_jack_conf" ] || exit 0
current_parameters=$(get_current_parameters)
wanted_parameters=$(cat "$backup_jack_conf")
rm "$backup_jack_conf"
rm "$tmp_pulse_file"

make_diff_parameters

[[ "$(current_value_of jack_started)" == 1 ]] && jack_was_started=true || jack_was_started=false

# reset the backup jack parameters in all cases
set_jack_parameters

if has_different_value jack_started;then
    if ! $jack_was_started;then
        start_jack
        reconfigure_pulseaudio
    else
        stop_jack
    fi
    exit 0
fi

# just leave if jack is not started and should not be
$jack_was_started || exit 0

# no jack parameters differences
if [ -z "$(echo "$diff_parameters"|grep -e ^/engine/ -e ^/driver/ -e ^/internals/)" ];then
    reconfigure_pulseaudio
    exit 0
fi

# JACK is started and should be, but not with the same parameters
stop_jack
start_jack
reconfigure_pulseaudio
exit 0
