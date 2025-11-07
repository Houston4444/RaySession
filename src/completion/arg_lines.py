HELP_ARGS = """
--help
--help-all
--help-control
--help-server
--help-session
--help-clients
"""

FIRST_ARG = """
--port
--detach
start
start_new
start_new_hidden
stop
list_daemons
get_port
get_root
get_pid
get_session_path
has_gui
has_local_gui
new_session
open_session
open_session_off
list_sessions
quit
change_root
set_terminal_command
list_session_templates
list_user_client_templates
list_factory_client_templates
remove_client_template
set_options
has_option
script_info
hide_script_info
script_user_action
has_attached_gui
auto_export_custom_names
export_custom_names
import_pretty_names
clear_pretty_names
save
save_as_template
take_snapshot
close
abort
duplicate
open_snapshot
rename
add_exec
add_factory_client_template
add_user_client_template
list_snapshots
list_clients
list_trashed_clients
set_notes
hide_notes
client
trashed_client
"""

SERVER_OPTIONS = """
bookmark_session_folder
desktops_memory
snapshots
session_scripts
gui_states
"""

YESNO = """
yes
no
"""

ADD_EXEC_OPS = """
ray_hack
not_start
prefix_mode:client_name
prefix_mode:session_name
prefix:
client_id:
"""

LIST_CLIENTS_FILTERS = """
started
active
auto_start
no_save_level
not_started
not_active
not_auto_start
not_no_save_level
"""

CLIENT_ARG = """
stop
kill
trash
start
resume
open
save
save_as_template
show_optional_gui
hide_optional_gui
get_properties
set_properties
set_custom_data
get_custom_data
set_tmp_data
get_tmp_data
list_files
list_snapshots
open_snapshot
is_started
get_pid
"""

TRASHED_CLIENT_ARG = """
restore
remove_definitely
remove_keep_files
"""

CLIENT_PROPS = """
executable:
environment:
arguments:
desktop_file:
label:
icon:
check_last_save:
ignored_extensions:
"""