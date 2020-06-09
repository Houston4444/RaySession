#!/bin/bash

has_pulse_jack(){
    # check if pulseaudio-module-jack is quite long (> 100ms on a correct machine)
    # So this state is stored in a tmp file.
    
    if [ -f "$tmp_pulse_file" ];then
        [[ "$(cat "$tmp_pulse_file")" == 0 ]] && return 0 || return 1
    fi
    
    which pulseaudio >/dev/null && pulseaudio --dump-modules|grep -q ^module-jack-
    return_code=$?
    echo $return_code > "$tmp_pulse_file"
    return $return_code
}


get_current_parameters(){
    $RAY_HOSTNAME_SENSIBLE && echo "hostname:$(hostname)"
    
    parameters_path="$tmp_dir/jack_current_parameters"

    if [ -f "$parameters_path" ];then
        daemon_pid=$(cat "$parameters_path"|grep ^daemon_pid:|cut -d':' -f2)
        [ -d "/proc/$daemon_pid" ] || rm "$parameters_path"
    fi
    
    if [ ! -f "$parameters_path" ];then
        # start the jack parameters checker daemon
        ./jack_checker_daemon.py &>/dev/null &
        
        for ((i=0; i<=50; i++));do
            sleep 0.1
            [ -f "$parameters_path" ] && break
            [ "$i" == 2 ] && ray_control script_info "$tr_waiting_jack_infos" >/dev/null
        done
        
        ray_control hide_script_info >/dev/null
    fi

    if [ -f "$parameters_path" ];then
        jack_parameters=$(cat "$parameters_path")
        if [[ "$1" == for_load ]];then
            echo "$jack_parameters"|grep -v ^"daemon_pid:"
        else
            echo "$jack_parameters"|grep -v -e ^"daemon_pid:" -e ^"reliable_infos:"
        fi
    fi
    
    if echo "$jack_parameters"|grep -q ^jack_started:1$ && has_pulse_jack && which jack_lsp >/dev/null;then
        all_jack_ports=$(jack_lsp)
        echo "pulseaudio_sinks:$(echo "$all_jack_ports"|grep ^"PulseAudio JACK Sink:"|wc -l)"
        echo "pulseaudio_sources:$(echo "$all_jack_ports"|grep ^"PulseAudio JACK Source:"|wc -l)"
    fi
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


set_jack_parameters(){
    parameters_files=$(mktemp)
    echo "$wanted_parameters" > "$parameters_files"
    ./jack_parameters.py "$parameters_files"
    rm "$parameters_files"
}


start_jack(){
    ray_control script_info "$tr_starting_jack"
    jack_control start &>/dev/null
    if ! jack_control status &>/dev/null;then
        ray_control script_info "$(tr_start_jack_failed_${ray_operation})"
        # session load is aborted, and script_info dialog will not be hidden
        exit 1
    fi
}


stop_jack(){
    if $RAY_SWITCHING_SESSION;then
        ray_control script_info "$tr_stopping_clients"
        ray_control clear_clients
    fi
    
    ray_control script_info "$tr_stopping_jack"
    jack_control stop &>/dev/null
}


set_samplerate(){
    jack_control dps rate "$(current_value_of /driver/rate)"
}


check_alsa_device(){
    full_device="$1"
    [ -z "$full_device" ] && return 0 # device is not set, should work in most cases
    
    device_and_index=${full_device#*:}
    device=${device_and_index%,*}
    index=${device_and_index##*,}
    
    command=aplay
    [[ "$2" == capture ]] && command=arecord
    
    if [[ "$device_and_index" =~ ',' ]];then
        LANG=C LC_ALL=C $command -l|grep -q ^"card .: ${device} \[.*\], device ${index}: "
    elif [[ "$device_and_index" =~ ^[0-9]+$ ]];then
        LANG=C LC_ALL=C $command -l|grep -q ^"card ${index}: "
    else
        LANG=C LC_ALL=C $command -l|grep -q ^"card .: ${device} \["
    fi
    
    return_code=$?
    unset full_device device_and_index device index command
    return $return_code
}


check_device(){
    case "$(wanted_value_of /engine/driver)" in
        alsa )
            if [[ "$(wanted_value_of /driver/duplex)" == "1" ]];then
                pb_device=$(wanted_value_of /driver/playback)
                if ! check_alsa_device "$pb_device";then
                    ray_control script_info "$(tr_device_not_connected_${ray_operation} "$pb_device")"
                    exit 1
                fi
                
                cp_device="$(wanted_value_of /driver/capture)"
                if ! check_alsa_device "$cp_device" capture;then
                    ray_control script_info "$(tr_device_not_connected_${ray_operation} "$cp_device")"
                    exit 1
                fi
            else
                pb_device="$(wanted_value_of /driver/device)"
                if ! check_alsa_device "$pb_device";then
                    ray_control script_info "$(tr_device_not_connected_${ray_operation} "$pb_device")"
                    exit 1
                fi
            fi
            ;;
        net )
            check_url=$(wanted_value_of /driver/multicast-ip)
            if [[ -n "$check_url" ]] && ! ping -c 1 "$check_url" &>/dev/null;then
                ray_control script_info "$(tr_device_not_connected_${ray_operation} "$check_url")"
                exit 1
            fi
            ;;
        * )
            true
            ;;
    esac
}
            

reconfigure_pulseaudio(){
    $RAY_MANAGE_PULSEAUDIO || return
    has_pulse_jack || return
    
    if [[ "$1" == "as_it_just_was" ]];then
        sources_channels=$(current_value_of pulseaudio_sources)
        sinks_channels=$(current_value_of pulseaudio_sinks)
    else
        sources_channels=$(wanted_value_of pulseaudio_sources)
        sinks_channels=$(wanted_value_of pulseaudio_sinks)
    fi
    
    if [[ "$1" == "as_it_just_was" ]] || (
            has_different_value pulseaudio_sinks || has_different_value pulseaudio_sources);then
        ray_control script_info "$(tr_reconfigure_pulseaudio "$sources_channels" "$sinks_channels")"
        ./reconfigure-pulse2jack.sh -c "$sources_channels" -p "$sinks_channels"
    fi
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
    if ! $RAY_HOSTNAME_SENSIBLE;then
        [[ "$1" == hostname ]] && return 1
    fi
    echo "$diff_parameters"|grep -q ^"$1"$
}


source locale.sh

session_jack_file="$RAY_SESSION_PATH/jack_parameters"

tmp_dir=/tmp/RaySession
[ -d "$tmp_dir" ] || mkdir -p "$tmp_dir"
backup_jack_conf="$tmp_dir/jack_backup_parameters"
tmp_pulse_file="$tmp_dir/has_pulse_jack"
