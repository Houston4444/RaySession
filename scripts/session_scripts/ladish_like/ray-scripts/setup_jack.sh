#!/bin/bash

wanted_value_of(){
    line=$(echo "$wanted_parameters"|grep ^"$1:"|head -n 1)
    echo "${line#*:}"
}


current_value_of(){
    line=$(echo "$current_parameters"|grep ^"$1:"|head -n 1)
    echo "${line#*:}"
}


has_different_value(){
    echo "$diff_parameters"|grep -q ^"$1"$
}

make_diff_parameters(){
    IFS=$'\n'
    
    diff_parameters=""
    for line in $wanted_parameters;do
        param="${line%%:*}"
        value="${line#*:}"
        
        current_line=$(echo "$current_parameters"|grep ^"${param}:")
        current_value="${current_line#*:}"
        
        [[ "$value" != "$current_value" ]] && diff_parameters+="$param
"
    done
    unset IFS
}


set_samplerate(){
    jack_control dps rate "$(current_value_of /driver/rate)"
}


set_jack_parameters(){
    parameters_files=$(mktemp)
    echo "$wanted_parameters" > "$parameters_files"
    "$jack_parameters_py" "$parameters_files"
    rm "$parameters_files"
}


start_jack(){
    ray_control script_info "Starting JACK"
    jack_control start
    if ! jack_control status;then
        ray_control script_info "Failed to start JACK.
Session open cancelled !"
        exit 1
    fi
}


stop_jack(){
    ray_control script_info "Stopping clients"
    ray_control clear_clients
    ray_control script_info "Stopping JACK"
    jack_control stop
}

reconfigure_pulseaudio(){
    if [[ "$1" == "as_it_just_was" ]];then
        sources_channels=$(current_value_of pulseaudio_sources)
        sinks_channels=$(current_value_of pulseaudio_sinks)
    else
        sources_channels=$(wanted_value_of pulseaudio_sources)
        sinks_channels=$(wanted_value_of pulseaudio_sinks)
    fi
    
    if [[ "$1" == "as_it_just_was" ]] || (
            has_different_value pulseaudio_sinks || has_different_value pulseaudio_sources);then
        ray_control script_info "Reconfigure PulseAudio
with $sources_channels inputs / $sinks_channels outputs."
        "$reconfigure_pa_script" -c "$sources_channels" -p "$sinks_channels"
    fi
}


############ SCRIPT START #############

source "$RAY_SCRIPTS_DIR/shared.sh" || exit 0

jack_parameters_py="$RAY_SCRIPTS_DIR/tools/jack_parameters.py"
reconfigure_pa_script="$RAY_SCRIPTS_DIR/tools/reconfigure-pulse2jack.sh"

# read current and session parameters, and diff between them
current_parameters=$(get_current_parameters)  # see shared.sh
wanted_parameters=$(cat "$RAY_SESSION_PATH/jack_parameters") || exit 0
make_diff_parameters

if [[ "$(current_value_of reliable_infos)" == 0 ]];then
    # no reliable JACK infos because JACK was started before the checker script
    stop_jack
    
    if has_different_value hostname;then
        has_different_value /driver/rate && set_samplerate
        start_jack
        reconfigure_pulseaudio as_it_just_was
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
    stop_jack
    
    if has_different_value hostname;then
        set_samplerate
        start_jack
        reconfigure_pulseaudio as_it_just_was
    else
        set_jack_parameters
        start_jack
        reconfigure_pulseaudio
    fi
    
    exit 0
fi

# Session last open was on another machine, continue normal way
has_different_value hostname && exit 0

if [ -z "$(echo "$diff_parameters"|grep -e ^/engine/ -e ^/driver/ -e ^/internals/)" ];then
    # no jack parameters differences, set only parameters if jack is stopped
    if [[ "$(current_value_of jack_started)" == 0 ]];then
        set_jack_parameters
        start_jack
    fi
    
    reconfigure_pulseaudio
else
    stop_jack
    set_jack_parameters
    start_jack
    reconfigure_pulseaudio
fi

exit 0
