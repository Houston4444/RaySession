#!/bin/bash

proxy_to_ray_hack(){
    client_id="$1"
    echo "  treating $client_id"
    c_project_path=$(ray_control client $client_id list_files)
    proxy_properties=$(ray_control client $client_id get_proxy_properties)
    
    # more than 1 path for this client, skip
    [[ $(echo "$c_project_path"|wc -l) == "1" ]] || continue
    
    # move the folder didn't work, skip
    if ! mv "$c_project_path" "${c_project_path}__bak";then
        echo "error while moving files, ignore it"
        continue
    fi
    
    echo "trash $client_id"
    ray_control client $client_id trash
    echo "remove_definitely $client_id"
    ray_control trashed_client $client_id remove_definitely
    
    exec_line=$(echo "$proxy_properties"|grep ^executable:)
    good_lines=$(echo "$proxy_properties"|grep -e ^arguments: -e ^no_save_level: -e ^config_file:)
    save_sig_line=$(echo "$proxy_properties"|grep ^save_signal:)
    stop_sig_line=$(echo "$proxy_properties"|grep ^stop_signal:)
    wait_win_line=$(echo "$proxy_properties"|grep ^wait_window:)

    # mmmh, on very old proxies, stop signal was always saved to SIGUSR1
    stop_sig=${stop_sig_line#*:}
    [[ "$stop_sig" == "10" ]] && stop_sig=15
    
    new_client_id=$(ray_control add_executable "${exec_line#*:}" ray_hack not_start client_id:${client_id})
    if [ -n "$new_client_id" ];then
        echo "set properties of new client '$new_client_id'"
        ray_control client $new_client_id set_properties "$good_lines
save_sig:${save_sig_line#*:}
stop_sig:$stop_sig
wait_win:${wait_win_line#*:}"
        rm -R "$c_project_path"
    else
        echo "Add executable failed, sorry, no more client"
    fi
    
    mv "${c_project_path}__bak" "$c_project_path"
}

all_sessions(){
    for session in $(ray_control list_sessions);do
        echo "____"
        echo "session:"$session
        ray_control open_session_off "$session" || continue

        clients=$(ray_control list_clients executable:ray-proxy)
        for client_id in $clients;do
            proxy_to_ray_hack "$client_id"
        done
    done
    ray_control save
}




export RAY_CONTROL_PORT=$(ray_control start_new_hidden)

IFS=$'\n'

all_sessions
ray_control quit
