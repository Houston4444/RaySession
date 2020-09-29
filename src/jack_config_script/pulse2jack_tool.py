#!/usr/bin/python3

import os
import shlex
import shutil
import subprocess
import sys
import tempfile

TMP_PA_CONTENTS = """
.fail

### Automatically restore the volume of streams and devices
load-module module-device-restore
load-module module-stream-restore
load-module module-card-restore

### Load unix protocol
load-module module-native-protocol-unix

### Automatically restore the default sink/source when changed by the user
### during runtime
### NOTE: This should be loaded as early as possible so that subsequent modules
### that look up the default sink/source get the right value
load-module module-default-device-restore

### Automatically move streams to the default sink if the sink they are
### connected to dies, similar for sources
load-module module-rescue-streams

### Make sure we always have a sink around, even if it is a null sink.
load-module module-always-sink
"""
PULSE_CONFIG_DIR = os.path.join(os.getenv('HOME'), '.pulse')
if os.getenv('PULSE_CONFIG_DIR'):
    PULSE_CONFIG_DIR = os.getenv('PULSE_CONFIG_DIR')


class Bridge:
    module_id = '0'
    type = 'source'
    name = ''
    channels = ''
    connected = 'yes'
    existing = False
    number_in_file = ''

    def __init__(self, bridge_type, name, channels, connected):
        if bridge_type.lower() == 'sink':
            self.type = 'sink'

        self.name = name

        if channels.isdigit() and int(channels) > 0:
            self.channels = channels

        if connected.lower() in ('false', 'no'):
            self.connected = 'no'

    def is_same_as(self, other)->bool:
        return bool(self.type == other.type
                    and self.name == other.name
                    and self.channels == other.channels
                    and self.connected == other.connected)

    def set_module_id(self, module_id: str):
        self.module_id = module_id

    def set_value_with_key(self, key: str, value: str):
        if key == 'name':
            self.name = value
        elif key == 'channels':
            if value.isdigit() and int(value) >= 1:
                self.channels = value
        elif key == 'connect':
            self.connected = value
    
    def get_load_module_string(self)->str:
        string = "load-module module-jack-%s" % self.type
        if self.channels:
            string += " channels=%s" % self.channels
        if self.connected:
            string += " connected=%s" % self.connected
        if self.name:
            string += " client_name=\"%s\"" % self.name.replace('"', '\\"')
        return string
    
    def get_save_string(self)->str:
        str_base = "pulseaudio_%s%s" % (self.type, self.number_in_file)
        save_list = []
        if self.name:
            save_list.append("%s_name=%s" % (str_base, self.name))
        if self.channels:
            save_list.append("%s_channels=%s" % (str_base, self.channels))
        if self.connected:
            save_list.append("%s_connect=%s" % (str_base, self.connected))
        return '\n'.join(save_list)
        

def rewrite_config_file(file_path: str, keys: dict):
    if not os.access(file_path, os.W_OK):
        sys.stderr.write("Impossible to write %s\n" % file_path)
        return

    contents = ""
    if os.path.isfile(file_path) and os.access(file_path, os.R_OK):
        file = open(file_path, 'r')
        contents = file.read()
        file.close()

    out_lines = []

    if contents:
        for line in contents.split('\n'):
            for key in keys:
                if line.startswith("%s =" % key):
                    break
            else:
                out_lines.append(line)

    for key in keys:
        out_lines.append("%s = %s" % (key, keys[key]))

    file = open(file_path, 'w')
    file.write('\n'.join(out_lines))
    file.close()

def init_pulse_config_files():
    client_keys = {"autospawn": "no"}
    daemon_keys = {"default-sample-format": "float32le",
                   "realtime-scheduling": "yes",
                   "rlimit-rttime": "-1",
                   "exit-idle-time": "-1"}

    rewrite_config_file("%s/client.conf" % PULSE_CONFIG_DIR, client_keys)
    rewrite_config_file("%s/daemon.conf" % PULSE_CONFIG_DIR, daemon_keys)

def start_pulseaudio():
    """Starts pulseaudio with custom properties"""
    tmp_pa = tempfile.NamedTemporaryFile(mode='w+t')
    tmp_pa.writelines(TMP_PA_CONTENTS)
    tmp_pa.seek(0)

    process = subprocess.run(["pulseaudio", "--daemonize", "--high-priority",
                              "--realtime", "--exit-idle-time=-1",
                              "--file=%s" % tmp_pa.name, "-n"])

    if process.returncode:
        sys.stdout.write("Failed to initialize PulseAudio!\n")
    else:
        sys.stdout.write("Initiated PulseAudio successfully!\n")

def get_wanted_bridges_from_str(input_parameters: str)->list:
    bridges = []

    for line in input_parameters.split('\n'):
        key, egal, value = line.partition('=')
        if not key.startswith('pulseaudio_'):
            continue

        key = key.replace('pulseaudio_', '', 1)

        if not key.startswith(('sink', 'source')):
            continue

        bridge_type = 'sink'
        if key.startswith('source'):
            bridge_type = 'source'

        key = key.replace(bridge_type, '', 1)
        number_in_file, underscore, subkey = key.partition('_')

        if not number_in_file:
            number_in_file = '0'
        elif number_in_file == 's':
            # ensure backward compatibility with pulse_audio_sinks
            # and pulse_audio_sources keys
            subkey = 'channels'
            if value == '0':
                continue
        if not number_in_file.isdigit():
            continue

        if not subkey in ('name', 'channels', 'connect'):
            continue

        for bridge in bridges:
            if (bridge.type == bridge_type
                    and bridge.number_in_file == number_in_file):
                bridge.set_value_with_key(subkey, value)
                break
        else:
            bridge = Bridge(bridge_type, '', '', '')
            bridge.number_in_file = number_in_file
            bridge.set_value_with_key(subkey, value)
            bridges.append(bridge)

    return bridges

def pactl_contents_to_bridge_list(pactl_contents: str)->list:
    """Converts the contents of `pactl list modules short`
to a list of Bridge class elements"""
    modules = []

    # parse the pactl list
    for line in pactl_contents.split('\n'):
        elements = line.split('\t')
        if len(elements) < 3:
            continue

        module_number, module_name, *rest = elements
        arguments_line = '\t'.join(rest)

        if module_name not in ('module-jack-sink', 'module-jack-source'):
            # not a pulseaudio JACK bridge module, no interest here
            continue

        module_type = module_name.replace('module-jack-', '')
        arguments = shlex.split(arguments_line)

        client_name = ""
        channels = ""
        connected = "yes"

        for argument in arguments:
            if argument.startswith('client_name='):
                client_name = argument.partition('=')[2]
            elif argument.startswith('channels='):
                channels = argument.partition('=')[2]
            elif argument.startswith('connect='):
                connected = argument.partition('=')[2]

        module = Bridge(module_type, client_name, channels, connected)
        module.set_module_id(module_number)
        modules.append(module)

    return modules

def get_existing_modules()->list:
    """reads loaded pulseaudio modules and returns them in a list of Bridges"""

    # will raise FileNotFoundError if pactl is missing
    # or subprocess.CalledProcessError if pulseaudio is not running
    pactl_contents = subprocess.check_output(
        ['pactl', 'list', 'modules', 'short']).decode()

    return pactl_contents_to_bridge_list(pactl_contents)

def get_save_string(existing_modules: list)->str:
    save_string = ''
    n_sink = 1
    n_source = 1
    for bridge in existing_modules:
        if bridge.type == 'sink':
            if n_sink > 1:
                bridge.number_in_file = str(n_sink)
            n_sink += 1
        elif bridge.type == 'source':
            if n_source > 1:
                bridge.number_in_file = str(n_source)
            n_source += 1

    return '\n'.join([b.get_save_string() for b in existing_modules]) 

def unload_and_load_modules(wanted_modules, existing_modules):
    """Unload unwanted PulseAudio JACK modules
        and load wanted modules, skipping theses one already bridged"""

    # disconnect unwanted modules
    for module in existing_modules:
        for bridge in wanted_modules:
            if bridge.is_same_as(module):
                bridge.existing = True
                sys.stderr.write(
                    'keep module-jack-%s "%s" because it is already running\n'
                    % (module.type, module.name))
                break
        else:
            sys.stderr.write('unload module-jack-%s "%s"\n'
                             % (module.type, module.name))
            subprocess.run(['pactl', 'unload-module', module.module_id])

    has_source = False
    has_sink = False

    # connect new bridges
    for bridge in wanted_modules:
        if bridge.type == 'source':
            has_source = True
        else:
            has_sink = True

        if bridge.existing:
            continue

        sys.stderr.write(
            'Adding module-jack-%s "%s"\n' % (bridge.type, bridge.name))
        process_args = ['pactl', 'load-module',
                        'module-jack-%s' % bridge.type]

        if bridge.channels:
            process_args.append('channels="%s"' % bridge.channels)
        if bridge.name:
            process_args.append('client_name="%s"'
                                % bridge.name.replace('"', '\\"'))
        if bridge.connected:
            process_args.append('connect="%s"' % bridge.connected)

        subprocess.run(process_args, stdout=subprocess.DEVNULL)

    if has_source:
        subprocess.run(['pactl', 'set-default-source', 'jack_in'])
    if has_sink:
        subprocess.run(['pactl', 'set-default-sink', 'jack_out'])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.stderr.write('argument required.\n')
        sys.exit(1)
    
    # init the pulse config files if needed
    init_pulse_config_files()

    if not shutil.which('pactl'):
        sys.stderr.write(
            'pactl is missing, please install pulseaudio !\n')
        sys.exit(1)

    pactl_prc = subprocess.run(
        ['pactl', 'list', 'modules', 'short'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    pactl_contents = pactl_prc.stdout.decode()
    existing_modules = pactl_contents_to_bridge_list(pactl_contents)
    
    if sys.argv[1] == '--save':
        if pactl_prc.returncode:
            sys.exit()
        sys.stdout.write(get_save_string(existing_modules))
        sys.stdout.write('\n')
        sys.exit()
    else:
        wanted_modules = get_wanted_bridges_from_str(sys.argv[1])
        if pactl_prc.returncode:
            start_pulseaudio(wanted_modules)
        else:
            unload_and_load_modules(wanted_modules, existing_modules)
    
