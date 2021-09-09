#!/bin/bash

executable=hydrogen

# check what to do with arguments
convert_sessions=false
convert_client_templates=false
convert_session_templates=false

for arg in "$@";do
    [[ "$arg" == sessions ]] && convert_sessions=true
    [[ "$arg" == client_templates ]] && convert_client_templates=true
    [[ "$arg" == session_templates ]] && convert_session_templates=true
done

if ! ($convert_sessions || $convert_client_templates || $convert_session_templates);then
    echo "nothing to do, use arguments"
    exit 0
fi

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

if $convert_sessions;then
    IFS=$'\n'

    for session in $(ray_control list_sessions);do
        unset IFS

        ray_control open_session_off "$session" 2>/dev/null
        
        clients=$(ray_control list_clients \
                    executable:$executable \
                    protocol:Ray-Hack \
                    prefix_mode:2 \
                    config_file:"\$RAY_SESSION_NAME.h2song" \
                    arguments:"-n -s \"\$CONFIG_FILE\"")
        
        if [ -z "$clients" ];then
            ray_control abort 2>/dev/null
            continue
        fi

        echo "treating session:$session"
        cd "$(ray_control get_session_path)"
        echo cd $PWD

        for client_id in $clients;do
            echo "  client:$client_id"

            folder="${session##*/}.$client_id"
            current_hsong_file="$folder/${session##*/}.h2song"

            if ! [ -f "$current_hsong_file" ];then
                echo "$current_hsong_file doesn't exists, skip"
                continue
            fi

            # here rename h2song file to match with how hydrogen works with NSM
            if ! mv "$folder/${session##*/}.h2song" "$folder/${session##*/}.$client_id.h2song";then
                echo "    impossible to rename h2song file, skip"
                continue
            fi

            # rename the folder with a _ prefix to prevent
            # future client remove to remove this folder
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
fi

if $convert_client_templates;then
    IFS=$'\n'
    for template in $(ray_control list_user_client_templates \
                        executable:$executable \
                        protocol:Ray-Hack \
                        prefix_mode:2 \
                        config_file:"\$RAY_SESSION_NAME.h2song" \
                        arguments:"-n -s \"\$CONFIG_FILE\"");do
        unset IFS
        tmp_session=$(mktemp -u)
        ray_control open_session_off "$tmp_session"
        cd "$tmp_session"

        client_id=$(ray_control add_user_client_template "$template" not_start)
        folder="${session##*/}.$client_id"
        current_hsong_file="$folder/${session##*/}.h2song"

        if ! [ -f "$current_hsong_file" ];then
            echo "$current_hsong_file doesn't exists, skip"
            ray_control abort
            continue
        fi

        # here rename h2song file to match with how hydrogen works with NSM
        if ! mv "$folder/${session##*/}.h2song" "$folder/${session##*/}.$client_id.h2song";then
            echo "    impossible to rename h2song file, skip"
            ray_control abort
            continue
        fi

        ray_control client $client_id save_as_template "$template"
        ray_control abort
    done
fi

if $convert_session_templates;then
    IFS=$'\n'
    for session_template in $(ray_control list_session_templates);do
        tmp_session=$(mktemp -u)
        ray_control open_session_off "$tmp_session"
        cd "$tmp_session"
        echo cd $PWD

        clients=$(ray_control list_clients \
                    executable:$executable \
                    protocol:Ray-Hack \
                    prefix_mode:2 \
                    config_file:"\$RAY_SESSION_NAME.h2song" \
                    arguments:"-n -s \"\$CONFIG_FILE\"")
        
        if [ -z "$clients" ];then
            ray_control abort 2>/dev/null
            continue
        fi

        echo "    treating session template:$session"
        
        for client_id in $clients;do
            echo "        client:$client_id"

            folder="${session##*/}.$client_id"
            current_hsong_file="$folder/${session##*/}.h2song"

            if ! [ -f "$current_hsong_file" ];then
                echo "        $current_hsong_file doesn't exists, skip"
                continue
            fi

            # here rename h2song file to match with how hydrogen works with NSM
            if ! mv "$folder/${session##*/}.h2song" "$folder/${session##*/}.$client_id.h2song";then
                echo "        impossible to rename h2song file, skip"
                continue
            fi

            # rename the folder with a _ prefix to prevent
            # future client remove to remove this folder
            if ! mv "$folder" _"$folder";then
                echo "        impossible to rename $folder, skip"
                continue
            fi

            # trash and remove hydrogen Ray-Hack client
            # files have been renamed, so it won't remove its files
            ray_control client $client_id trash
            ray_control trashed_client $client_id remove_definitely

            mv _"$folder" "$folder"

            ray_control add_executable $executable client_id:$client_id not_start
        done

        # save the session and update the template
        ray_control save
        ray_control save_as_template "$session_template"
        ray_control abort
    done
fi

$reput_session_scripts && ray_control set_options session_scripts
$reput_bookmarks && ray_control set_options bookmark_session_folder
