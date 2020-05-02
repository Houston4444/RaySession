#!/bin/bash

############ SCRIPT START #############

# exit 0 means load session after script
# else the session open will be cancelled

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0

# read current and session parameters, and diff between them
current_parameters=$(get_current_parameters)

[ -f "$session_jack_file" ] && wanted_parameters=$(cat "$session_jack_file")
make_diff_parameters

[[ "$(current_value_of jack_started)" == 1 ]] && jack_was_started=true || jack_was_started=false

if ! $RAY_SWITCHING_SESSION;then
    # Very strange if it not already exists
    mkdir -p /tmp/RaySession
    echo "$current_parameters" > /tmp/RaySession/jack_backup_parameters
fi


# no reliable JACK infos because JACK was started before the checker script
if [[ "$(current_value_of reliable_infos)" == 0 ]];then
    $jack_was_started && stop_jack
    
    if has_different_value hostname;then
        has_different_value /driver/rate && set_samplerate
        start_jack
        $jack_was_started && reconfigure_pulseaudio as_it_just_was
    else
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
    $jack_was_started && stop_jack
    
    if has_different_value hostname;then
        set_samplerate
        start_jack
        $jack_was_started && reconfigure_pulseaudio as_it_just_was
    else
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
        set_jack_parameters
        start_jack
    fi
    
    reconfigure_pulseaudio
else
    $jack_was_started && stop_jack
    set_jack_parameters
    start_jack
    reconfigure_pulseaudio
fi

exit 0
