#!/bin/bash

############ SCRIPT START #############

# exit 0 means load session after script
# else the session open will be cancelled

cd "$(dirname "`readlink -f "$(realpath "$0")"`")"
source shared.sh || exit 0

ray_operation=load

# read current and session parameters, and diff between them
current_parameters=$(get_current_parameters)

[ -f "$session_jack_file" ] && wanted_parameters=$(cat "$session_jack_file")
make_diff_parameters

[[ "$(current_value_of jack_started)" == 1 ]] && jack_was_started=true || jack_was_started=false

# save the current configuration to can restore it (only if we are not in a switch situation)
$RAY_SWITCHING_SESSION || echo "$current_parameters" > "$backup_jack_conf"


# no reliable JACK infos because JACK was started before the checker script
if [[ "$(current_value_of reliable_infos)" == 0 ]];then
    if has_different_value hostname;then
        $jack_was_started && stop_jack
        has_different_value /driver/rate && set_samplerate
        start_jack
        $jack_was_started && reconfigure_pulseaudio as_it_just_was
    else
        check_device
        $jack_was_started && stop_jack
        set_jack_parameters
        start_jack
        reconfigure_pulseaudio
    fi
    
    exit 0
fi

# JACK should not be started, continue normal way even if JACK is started
[[ "$(wanted_value_of jack_started)" == 0 ]] && exit 0

# Session uses another samplerate than the current one, re-start JACK and go
if has_different_value /driver/rate;then
    if has_different_value hostname;then
        $jack_was_started && stop_jack
        set_samplerate
        start_jack
        $jack_was_started && reconfigure_pulseaudio as_it_just_was
    else
        check_device
        $jack_was_started && stop_jack
        set_jack_parameters
        start_jack
        reconfigure_pulseaudio
    fi
    
    exit 0
fi

# Session last open was on another machine, continue normal way
if has_different_value hostname;then
    $jack_was_started || start_jack
    exit 0
fi

# no jack parameters differences, set only parameters if jack is stopped
if [ -z "$(echo "$diff_parameters"|grep -e ^/engine/ -e ^/driver/ -e ^/internals/)" ];then
    if ! $jack_was_started;then
        check_device
        set_jack_parameters
        start_jack
    fi
    
    reconfigure_pulseaudio
else
    check_device
    $jack_was_started && stop_jack
    set_jack_parameters
    start_jack
    reconfigure_pulseaudio
fi

exit 0
