#!/bin/bash

get_property(){
# $properties must be set before
line=$(echo "$properties"|grep -m 1 ^"$1:")
echo "${line#*:}"
}

# read arguments
replace_jackpatch=false
if [[ "$1" == '--replace-jackpatch' ]];then
    replace_jackpatch=true
    shift
fi

# we need to know the script dir to launch the python script
# that writes connections file
bash_dir=`realpath "$(dirname "${BASH_SOURCE[0]}")"`

# get the session to convert
# if no argument, the current session is choose
session="$1"
if [ -z "$session" ];then
    session=$(ray_control get_session_path)
    if [ -z "$session" ];then
        echo "No session loaded, nothing to do"
        exit
    fi
fi

# better to not use session_scripts and bookmark options
# for performance and security
# during the execution of this script
reput_session_scripts=false
reput_bookmarks=false
ray_control has_option session_scripts && reput_session_scripts=true
ray_control has_option bookmark_session_folder && reput_bookmarks=true
ray_control set_options not_session_scripts not_bookmark_session_folder

# close and re-open the session
# It prevents to have to save the session with clients off
ray_control close
ray_control open_session_off "$session"
ray_control take_snapshot "Just before NSM conversion"

cd "$(ray_control get_session_path)"

# in bash, init empty vars is unneeded, that is true ;)
nsm_file_contents=''
connections_file_old=''
connections_file_new=''
group_replaces=''
rayjackpatch_client_id=''

# list clients and operate on them
for client_id in $(ray_control list_clients);do
    # change the client prefix to change their working directory
    # and adapt it to the nsmd way: client_name.client_id
    ray_control client $client_id change_prefix client_name
    
    # read all needed client properties
    properties=$(ray_control client "$client_id" get_properties)
    executable=$(get_property executable)
    client_name=$(get_property name)
    protocol=$(get_property protocol)
    jack_naming=$(get_property jack_naming)
    jack_name=$(get_property jack_name)

    case $protocol in
        NSM)
            if [[ "$executable" == ray-jackpatch ]];then
                connections_file="$client_name.$client_id.xml"
                rayjackpatch_client_id="$client_id"
                continue
            fi
            nsm_file_contents+="$client_name:$executable:$client_id\n"
            ;;
        Ray-Hack)
            # we will adapt the Ray-Hack client with nsm-proxy
            arguments=$(get_property arguments|sed 's/$RAY_JACK_CLIENT_NAME/$NSM_CLIENT_ID/g')
            config_file=$(get_property config_file|sed "s/\$RAY_SESSION_NAME/${session_path##*/}/g")
            save_sig=$(get_property save_sig)
            stop_sig=$(get_property stop_sig)
            label=$(get_property label)

            # save the nsm-proxy config file contents
            proxy_contents="executable
	$executable
arguments
	$arguments
config file
	$config_file
save signal
	$save_sig
stop signal
	$stop_sig
label
	$label
"
            linkdir="NSM Proxy.$client_id"
            if [ -d "$linkdir" && -L "$linkdir" ] && [[ "$(readlink "$linkdir")" == "$client_name.$client_id" ]];then
                echo "$linkdir already linked, keep it"
            
                # link the NSM Proxy new directory to the Ray-Hack client dir
            elif ln -s -r "$client_name.$client_id" "NSM Proxy.$client_id";then
                echo "$proxy_contents" > "NSM Proxy.$client_id/nsm-proxy.config"
                nsm_file_contents+="NSM Proxy:nsm-proxy:$client_id\n"
            else
                echo "impossible to link $client_name.$client_id to NSM Proxy.$client_id"
            fi
            ;;
    esac
    
    if [[ "$jack_naming" != 1 ]];then
        # the way to name JACK clients is different in RaySession and NSM
        # in NSM, long JACK naming is used,
        # JACK client is named this way: client_name.client_id
        # in RS, by default it is only:
        #     client_name (+ _N) if client_id ends with digits
        ray_control client $client_id set_properties jack_naming:1

        # a long string with jack client names will be sent as argument to
        # the python script which add new connections to the config file
        group_replaces+="old_name:$jack_name
new_name:$client_name.$client_id
"
    fi

done

jackpatch_id=nWASRAY

if $replace_jackpatch and [ -n "$rayjackpatch_client_id" ];then
    # remove ray-jackpatch from session and replace it with jackpatch
    ray_control client $rayjackpatch_client_id trash
    ray_control add_executable jackpatch not_start client_id:$jackpatch_id prefix_mode:client_name
fi

if [ -n "$connections_file" ];then
    # get the connections as written by the NSM jackpatch
    # Note it will also update the ray-jackpatch file with new connections
    conns=`"$bash_dir/connections_nsm_adapter.py" "$connections_file" "$group_replaces"`
    
    if $replace_jackpatch;then
        # write the jackpatch connections file and add jackpatch to the NSM session
        echo "$conns" > JACKPatch.$jackpatch_id.jackpatch
        nsm_file_contents="JACKPatch:jackpatch:$jackpatch_id
$nsm_file_contents"
    fi
fi

# save and close session
# very important to save because client prefixes have been moved
ray_control close

# write the NSM session file
echo -e "$nsm_file_contents" > session.nsm

# reput options unset at the script start
$reput_session_scripts && ray_control set_options session_scripts
$reput_bookmarks && ray_control set_options bookmark_session_folder

echo "Done."
