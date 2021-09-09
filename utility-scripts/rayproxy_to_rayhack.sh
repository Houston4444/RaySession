#!/bin/bash

print_help(){
    echo "usage: $1 arguments
    where options can be
        --help          print this help
        all_sessions    convert ray-proxy clients to RayHack in all sessions
        all_templates   convert all ray-proxy templates to Ray-Hack
        running_client CLIENT_ID
                convert running CLIENT_ID to ray_hack if it is a ray-proxy
"
}

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
    
    normal_lines=$(ray_control client $client_id get_properties|grep -e ^label: -e ^description: -e ^icon: -e ^desktop_file:)
    exec_line=$(echo "$proxy_properties"|grep ^executable:)
    good_lines=$(echo "$proxy_properties"|grep -e ^arguments: -e ^no_save_level:)
    save_sig_line=$(echo "$proxy_properties"|grep ^save_signal:)
    stop_sig_line=$(echo "$proxy_properties"|grep ^stop_signal:)
    wait_win_line=$(echo "$proxy_properties"|grep ^wait_window:)
    config_file_line=$(echo "$proxy_properties"|grep ^config_file:)

    config_file="${config_file_line#*:}"
    if [ -z "$config_file" ] && [[ "${save_sig_line#*:}" != "0" ]];then
        config_file=anything
    fi

    # mmmh, on very old proxies, stop signal was always saved to SIGUSR1
    stop_sig=${stop_sig_line#*:}
    [[ "$stop_sig" == "10" ]] && stop_sig=15
    
    new_client_id=$(ray_control add_executable "${exec_line#*:}" ray_hack not_start client_id:${client_id})
    if [ -n "$new_client_id" ];then
        echo "set properties of new client '$new_client_id'"
        ray_control client $new_client_id set_properties "$good_lines
config_file:${config_file}
save_sig:${save_sig_line#*:}
stop_sig:$stop_sig
wait_win:${wait_win_line#*:}
$normal_lines"
        rm -R "$c_project_path"
    else
        echo "Add executable failed, sorry, no more client"
    fi
    
    mv "${c_project_path}__bak" "$c_project_path"
}

all_sessions(){
    IFS=$'\n'
    
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

all_templates(){
    ray_control open_session_off $(mktemp -u)

    IFS=$'\n'

    for client_template in $(ray_control list_user_client_templates);do
        echo "  client_template:$client_template"
        client_id=$(ray_control add_user_client_template "$client_template" not_start) || continue
        echo "  client_id:$client_id"
        if ray_control client $client_id get_properties|grep ^executable:ray-proxy;then
            echo "     ray-proxy -> Ray-Hack"
            proxy_to_ray_hack $client_id
            echo "      save as template $client_template"
            ray_control client $client_id save_as_template "$client_template"
        fi
        ray_control client $client_id trash
        ray_control trashed_client $client_id remove_definitely
    done
}

argument=$1
shift
case $argument in
    all_sessions|all_templates)
        export RAY_CONTROL_PORT=$(ray_control start_new_hidden)
        $argument
        ray_control quit
    ;;
    running_client)
        client_id="$1"
        [ -z "$client_id" ] && print_help && exit 1
        echo -n "session_path:"
        ray_control get_session_path || exit 1
        if ! ray_control list_clients|grep ^$client_id$;then
            echo "no client with $client_id client_id"
            exit 1
        fi
        ray_control client "$client_id" stop
        proxy_to_ray_hack "$client_id"
    ;;
    --help )
        print_help
    ;;
    *)
        print_help
        exit 1
esac
