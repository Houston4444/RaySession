#!/bin/bash

get_property(){
# $properties must be set before
line=$(echo "$properties"|grep ^"$1:")
echo "${line#*:}"
}

bash_dir=`realpath "$(dirname "${BASH_SOURCE[0]}")"`

session_path=$(ray_control get_session_path)
if [ -z "$session_path" ];then
    echo "No session loaded, nothing to do"
    exit
fi

cd "$session_path" || exit 1

nsm_file_contents=""
connections_file_old=""
connections_file_new=''
group_replaces=""

for client_id in $(ray_control list_clients);do
    ray_control client $client_id is_started && ray_control client $client_id stop
    ray_control client $client_id change_prefix client_name
    properties=$(ray_control client "$client_id" get_properties)
    executable=$(get_property executable)
    client_name=$(get_property name)
    protocol=$(get_property protocol)
    long_jack_naming=$(get_property long_jack_naming)
    jack_name=$(get_property jack_name)

    case $protocol in
        NSM)
            if [[ "$executable" == ray-jackpatch ]];then
                connections_file="$client_name.$client_id.xml"
                continue
            fi
            nsm_file_contents+="$client_name:$executable:$client_id\n"
            ;;
        Ray-Hack)
            arguments=$(get_property arguments|sed 's/$RAY_JACK_CLIENT_NAME/$NSM_CLIENT_ID')
            config_file=$(get_property config_file|sed "s/\$RAY_SESSION_NAME/${session_path##*/}/g")
            save_sig=$(get_property save_sig)
            stop_sig=$(get_property stop_sig)
            label=$(get_property label)

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
            mv "$client_name.$client_id" "NSM Proxy.$client_id"
            echo "$proxy_contents" > "NSM Proxy.$client_id/nsm-proxy.config"
            nsm_file_contents+="NSM Proxy:nsm-proxy:$client_id\n"
            ;;
    esac
    
    if [[ "$long_jack_naming" != true ]];then
        ray_control client $client_id set_properties long_jack_naming:true
        group_replaces+="old_name:$jack_name
new_name:$client_name.$client_id
"
    fi

done

if [ -n "$connections_file" ];then
    echo "$connections_file"
    echo "$group_replaces"
    conns=`"$bash_dir/connections_nsm_adapter.py" "$connections_file" "$group_replaces"`
    echo "$conns" > JACKPatch.nWASRAY.jackpatch
    nsm_file_contents="JACKPatch:jackpatch:nWASRAY
$nsm_file_contents"
fi

ray_control close

echo -e "$nsm_file_contents" > session.nsm

echo "Done."
