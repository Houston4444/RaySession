#!/bin/bash

get_value(){
# be careful that $properties is correctly set on the good client
line=$(echo "$properties"|grep ^"$1:")
echo "${line#*:}"
}

executable=hydrogen

# check if hydrogen factory template uses NSM
hydro_nsm_templates=$(ray_control list_factory_client_templates executable:$executable protocol:NSM)

if [ -z "$hydro_nsm_templates" ];then
    echo "Your current $executable version seems to be too old to have correct NSM support."
    exit 1
fi

# better to not use session_scripts and bookmark options for performance
# during the execution of this script
# first, remember if script has to reput them once done
reput_session_scripts=false
reput_bookmarks=false
ray_control has_option session_scripts && reput_session_scripts=true
ray_control has_option bookmark_session_folder && reput_bookmarks=true
ray_control set_options not_session_scripts not_bookmark_session_folder

IFS=$'\n'

for session in $(ray_control list_sessions);do
    unset IFS
    ray_control open_session_off "$session" 2>/dev/null
    clients=$(ray_control list_clients executable:$executable protocol:Ray-Hack)
    if [ -z "$clients" ];then
        ray_control abort 2>/dev/null
        continue
    fi

    echo "treating session:$session"
    cd "$(ray_control get_session_path)"

    for client_id in $clients;do
        echo "  client:$client_id"
        properties=$(ray_control client $client_id get_properties)
        project_files=$(ray_control client $client_id list_files)

        arguments=`get_value arguments`
        if [[ "$arguments" != "-s \"\$CONFIG_FILE\"" ]];then
            echo "    arguments are not standard:$arguments"
            continue
        fi

        config_file=`get_value config_file`
        if [[ "$config_file" != '$RAY_SESSION_NAME.h2song' ]];then
            echo "    config file is not standard, skip"
            continue
        fi

        prefix_mode=`get_value prefix_mode`
        if [[ "$prefix_mode" != "2" ]];then
            echo "    prefix mode not standard, skip"
            continue
        fi

        folder="${session##*/}.$client_id"

        # here rename h2song file to match with how hydrogen works with NSM
        if ! mv "$folder/${session##*/}.h2song" "$folder/${session##*/}.$client_id.h2song";then
            echo "impossible to rename h2song file, skip"
            continue
        fi

        # rename the folder with a _ prefix to prevent
        if ! mv "$folder" _"$folder";then
            echo "    impossible to rename $folder, skip"
            continue
        fi

        # trash and remove hydrogen Ray-Hack client
        # files have been renamed, so it won't remove its files
        ray_control client $client_id trash
        ray_control trashed_client $client_id remove_definitely

        mv _"$folder" "$folder"

        ray_control add_executable $executable client_id:$client_id not_start
    done
done

ray_control close

IFS=$'\n'
for template in $(ray_control list_user_client_templates executable:$executable protocol:Ray-Hack);do
    unset IFS
    tmp_session=$(mktemp -u)
    ray_control open_session_off "$tmp_session"
    cd "$tmp_session"

    client_id=$(ray_control add_user_client_template "$template" not_start)
    # same schema

    ray_control client $client_id save_as_template "$template"
    ray_control abort
done

IFS=$'\n'
for session_template in $(ray_control list_session_templates);do
    tmp_session=$(mktemp -u)
    ray_control open_session_off "$tmp_session"
    cd "$tmp_session"

    clients=$(ray_control list_clients executable:$executable protocol:Ray-Hack)
    if [ -z "$clients" ];then
        ray_control abort 2>/dev/null
        continue
    fi

    echo "treating session template:$session"

    # same schema

    ray_control save
    ray_control save_as_template "$session_template"
    ray_control abort
done


reput_session_scripts && ray_control set_options session_scripts
reput_bookmarks && ray_control set_options bookmark_session_folder
