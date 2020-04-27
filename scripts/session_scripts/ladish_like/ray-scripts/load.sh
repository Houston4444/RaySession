#!/bin/bash

finished(){
    ray_control hide_script_info
    ray_control run_step
    exit 0
}


wanted_value_of(){
    line=$(echo "$wanted_parameters"|grep ^"$1:"|head -n 1)
    echo "${line#*:}"
}


current_value_of(){
    line=$(echo "$current_parameters"|grep ^"$1:"|head -n 1)
    echo "${line#*:}"
}


has_different_value(){
    [[ `wanted_value_of "$1"` != `current_value_of "$1"` ]] \
        && return 0 || return 1
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
    if ! jack_control start;then
        ray_control script_info "Failed to start JACK. Session Aborted !"
        ray_control abort
        sleep 1
        ray_control hide_script_info
        exit 
    fi
}


stop_jack(){
    ray_control script_info "Stopping clients"
    ray_control clear_clients
    ray_control script_info "Stopping PulseAudio"
    pulseaudio -k
    ray_control script_info "Stopping JACK"
    jack_control stop
}


reconfigure_pulseaudio(){
    if has_different_value pulseaudio_sinks || has_different_value pulseaudio_sources;then
        ray_control script_info "Reconfigure PulseAudio with $(wanted_value_of pulseaudio_sources) inputs"
        "$reconfigure_pa_script" -c "$(wanted_value_of pulseaudio_sources)" -p "$(wanted_value_of pulseaudio_sinks)"
    fi
}


############ SCRIPT START #############
source "$RAY_SCRIPTS_DIR/shared.sh" || finished

jack_parameters_py="$RAY_SCRIPTS_DIR/tools/jack_parameters.py"
reconfigure_pa_script="$RAY_SCRIPTS_DIR/tools/reconfigure-pulse2jack.sh"

# read current and session parameters
current_parameters=$(get_current_parameters)
wanted_parameters=$(cat "$RAY_SESSION_PATH/jack_parameters") || finished

# JACK should not be started, continue normal way even if JACK is started
[[ "$(wanted_value_of jack_started)" == 0 ]] && finished

# Session uses another samplerate than the current one, re-start JACK and go
if has_different_value /driver/rate;then
    stop_jack
    
    if has_different_value hostname;then
        set_samplerate
        start_jack
    else
        set_jack_parameters
        start_jack
        reconfigure_pulseaudio
    fi
    
    finished
fi

# Session last open was on another machine, continue normal way
has_different_value hostname && finished

same_setup=true

for parameter in /engine/driver /engine/realtime /engine/realtime-priority \
                 /engine/self-connect-mode /engine/slave-drivers /driver/period \
                 /driver/nperiods /driver/inchannels /driver/outchannels \
                 /internals/audioadapter/device;do
    if has_different_value "$parameter";then
        same_setup=false
        break
    fi
done

if $same_setup;then
    [[ "$(current_value_of jack_started)" == 0 ]] && start_jack
    reconfigure_pulseaudio
    finished
else
    stop_jack
    set_jack_parameters
    start_jack
    reconfigure_pulseaudio
    finished
fi
