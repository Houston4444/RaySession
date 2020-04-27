#!/bin/bash

get_current_parameters(){
    echo "hostname:$(hostname)"

    all_jack_ports=$(jack_lsp)
    echo "pulseaudio_sinks:$(echo "$all_jack_ports"|grep ^"PulseAudio JACK Sink:"|wc -l)"
    echo "pulseaudio_sources:$(echo "$all_jack_ports"|grep ^"PulseAudio JACK Source:"|wc -l)"

    parameters_path="/tmp/RaySession/jack_current_parameters"

    if [ -f "$parameters_path" ];then
        current_parameters=$(cat "$parameters_path")
        daemon_pid=$(echo "$current_parameters"|grep ^daemon_pid:|cut -d':' -f2)
        
        if [ -d "/proc/$daemon_pid" ];then
            echo "$current_parameters"
            return 0
        fi
        
        rm "$parameters_path"
    fi

    ray_control script_info "Waiting for JACK infos..." >/dev/null
    
    # start the jack parameters checker daemon
    "$RAY_SCRIPTS_DIR/tools/jack_parameters_daemon.py" &>/dev/null &
    for ((i=0; i<=50; i++));do
        sleep 0.1
        [ -f "$parameters_path" ] && break
    done
    
    ray_control hide_script_info >/dev/null

    [ -f "$parameters_path" ] && cat "$parameters_path"
    return 0
}
