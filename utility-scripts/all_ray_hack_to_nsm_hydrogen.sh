#!/bin/bash

hydro_rh_to_nsm(){
    # variables 'session' and 'client_id' have to be set
    # session must be open
    # current directory must be in session path
    folder="${session##*/}.$client_id"
    current_hsong_file="$folder/${session##*/}.h2song"

    if ! [ -f "$current_hsong_file" ];then
        echo "$current_hsong_file doesn't exists, skip"
        return 1
    fi

    # here rename h2song file to match with how hydrogen works with NSM
    if ! mv "$folder/${session##*/}.h2song" "$folder/${session##*/}.$client_id.h2song";then
        echo "    impossible to rename h2song file, skip"
        return 1
    fi

    # trash and remove hydrogen Ray-Hack client
    ray_control client $client_id trash
    ray_control trashed_client $client_id remove_keep_files

    # add the new hydrogen NSM client
    ray_control add_executable $executable client_id:$client_id not_start
}

# check what to do with arguments
convert_current_session=false
convert_sessions=false
convert_client_templates=false
convert_session_templates=false

for arg in "$@";do
    [[ "$arg" == sessions ]] && convert_sessions=true
    [[ "$arg" == client_templates ]] && convert_client_templates=true
    [[ "$arg" == session_templates ]] && convert_session_templates=true
done

if ! ($convert_sessions || $convert_client_templates || $convert_session_templates);then
    convert_current_session=true
fi

executable=hydrogen
config_file="\$RAY_SESSION_NAME.h2song"
arguments="-n -s \"\$CONFIG_FILE\""

list_filters[0]="executable:$executable"
list_filters[1]="protocol:Ray-Hack"
list_filters[2]="prefix_mode:2"
list_filters[3]="config_file:$config_file"
list_filters[4]="arguments:$arguments"

# check if hydrogen factory template uses NSM
hydro_nsm_templates=$(ray_control list_factory_client_templates executable:$executable protocol:NSM)

if [ -z "$hydro_nsm_templates" ];then
    echo "Your current $executable version seems to be too old to have correct NSM support."
    exit 1
fi

# better to not use session_scripts and bookmark options
# for performance and security
# during the execution of this script
reput_session_scripts=false
reput_bookmarks=false

if ! $convert_current_session;then
    # no need to unset session_scripts and bookmarks
    # if we only work in the current session
    # because, in this case, session will not be saved or closed
    ray_control has_option session_scripts && reput_session_scripts=true
    ray_control has_option bookmark_session_folder && reput_bookmarks=true
    ray_control set_options not_session_scripts not_bookmark_session_folder
fi

if $convert_current_session;then
    echo "proceed in the current session"
    session=$(ray_control get_session_path)
    if [ -z "$session" ];then
        echo "no arguments, no running session, nothing to do !"
        exit 1
    fi

    clients=$(ray_control list_clients "${list_filters[@]}")

    if [ -z "$clients" ];then
        echo "no matching client in the current session, nothing to do !"
        exit 1
    fi

    cd "$session"

    for client_id in $clients;do
        echo "    client:$client_id"
        ray_control client $client_id stop
        hydro_rh_to_nsm
    done
fi

if $convert_sessions;then
    echo "proceed in all sessions"
    IFS=$'\n'

    for session in $(ray_control list_sessions);do
        unset IFS

        ray_control open_session_off "$session" 2>/dev/null
        
        clients=$(ray_control list_clients "${list_filters[@]}")
        
        if [ -z "$clients" ];then
            ray_control abort 2>/dev/null
            continue
        fi

        echo "treating session:$session"
        cd "$(ray_control get_session_path)"
        echo cd $PWD

        for client_id in $clients;do
            echo "  client:$client_id"
            hydro_rh_to_nsm
        done
    done

    ray_control close
fi

if $convert_client_templates;then
    echo "proceed in all client templates"

    IFS=$'\n'
    for template in $(ray_control list_user_client_templates "${list_filters[@]}");do
        unset IFS
        session=$(mktemp -u)
        ray_control open_session_off "$session"
        cd "$session"

        client_id=$(ray_control add_user_client_template "$template" not_start)
        hydro_rh_to_nsm
        ray_control client $client_id save_as_template "$template"
        ray_control abort
    done
fi

if $convert_session_templates;then
    echo "proceed in all session templates"

    IFS=$'\n'
    for session_template in $(ray_control list_session_templates);do
        session=$(mktemp -u)
        ray_control open_session_off "$session"
        cd "$session"
        echo cd $PWD

        clients=$(ray_control list_clients "${list_filters[@]}")
        
        if [ -z "$clients" ];then
            ray_control abort 2>/dev/null
            continue
        fi

        echo "    treating session template:$session"

        for client_id in $clients;do
            echo "        client:$client_id"
            hydro_rh_to_nsm
        done

        # save the session and update the template
        ray_control save
        ray_control save_as_template "$session_template"
        ray_control abort
    done
fi

$reput_session_scripts && ray_control set_options session_scripts
$reput_bookmarks && ray_control set_options bookmark_session_folder
