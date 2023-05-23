import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, TypedDict
import sys

from PyQt5.QtCore import QProcess, QCoreApplication
from PyQt5.QtXml import QDomDocument, QDomElement

import ray
from daemon_tools import (
    TemplateRoots,
    get_git_default_un_and_ignored,
    AppTemplate)
import ardour_templates
from client import Client

if TYPE_CHECKING:
    from session import Session


_translate = QCoreApplication.translate


class NsmDesktopExec(TypedDict):
    executable: str
    name: str
    desktop_file: str
    nsm_capable: bool
    skipped: bool
    

def _get_search_template_dirs(factory: bool) -> list[Path]:
        if factory:
            # search templates in /etc/xdg (RaySession installed)
            templates_root = Path(TemplateRoots.factory_clients_xdg)

            # search templates in source code
            if not templates_root.is_dir():
                templates_root = Path(TemplateRoots.factory_clients)

            if (templates_root.is_dir()
                    and os.access(templates_root, os.R_OK)):
                return sorted([t for t in templates_root.iterdir()])

            return []

        return [Path(TemplateRoots.user_clients)]

def _get_nsm_capable_execs_from_desktop_files() -> list[NsmDesktopExec]:
    ''' returns a list of dicts
        {'executable': str,
            'name': str,
            'desktop_file': str,
            'nsm_capable': True,
            'skipped': False} '''

    desk_path_list = (
        '%s/.local' % os.getenv('HOME'),
        '/usr/local',
        '/usr')

    application_dicts = list[NsmDesktopExec]()

    lang = os.getenv('LANG')
    lang_strs = ("[%s]" % lang[0:5], "[%s]" % lang[0:2], "")

    for desk_path in desk_path_list:
        full_desk_path = "%s/share/applications" % desk_path

        if not os.path.isdir(full_desk_path):
            # applications folder doesn't exists
            continue

        if not os.access(full_desk_path, os.R_OK):
            # no permission to read this applications folder
            continue

        for root, dirs, files in os.walk(full_desk_path):
            for f in files:
                if not f.endswith('.desktop'):
                    continue

                if f in [apd['desktop_file'] for apd in application_dicts]:
                    # desktop file already seen in a prior desk_path
                    continue

                full_desk_file = os.path.join(root, f)
                
                try:
                    file = open(full_desk_file, 'r')
                    contents = file.read()
                except:
                    continue

                executable = ''
                has_nsm_mention = False
                nsm_capable = True
                name = ''
                
                for line in contents.splitlines():
                    if line.startswith('Exec='):
                        executable_and_args = line.partition('=')[2].strip()
                        executable = executable_and_args.partition(' ')[0]
                    
                    elif line.lower().startswith('x-nsm-capable='):
                        has_nsm_mention = True
                        value = line.partition('=')[2]
                        nsm_capable = bool(value.strip().lower() == 'true')
                    
                    elif line.startswith('Name='):
                        name = line.partition('=')[2].strip()

                if (has_nsm_mention and executable
                        and shutil.which(executable)):
                    # prevent several desktop files with same executable
                    if executable in [apd['executable']
                                        for apd in application_dicts]:
                        continue

                    name = executable
                    name_found = False
                    
                    for lang_str in lang_strs:
                        for line in contents.splitlines():
                            if line.startswith('Name%s=' % lang_str):
                                name = line.partition('=')[2].strip()
                                name_found = True
                                break
                        if name_found:
                            break

                    # 'skipped' key may be set to True later,
                    # if a template does not want to be erased
                    # by the template created
                    # with this .desktop file.
                    application_dicts.append(
                        {'executable': executable,
                            'name': name,
                            'desktop_file': f,
                            'nsm_capable': nsm_capable,
                            'skipped': False})
    
    return [a for a in application_dicts if a['nsm_capable']]
    
def _rewrite_user_templates_file(
        content: QDomElement, templates_file: Path) -> bool:
    if not os.access(templates_file, os.W_OK):
        return False

    file_version = content.attribute('VERSION')

    if (ray.version_to_tuple(file_version)
            >= ray.version_to_tuple(ray.VERSION)):
        return False

    content.setAttribute('VERSION', ray.VERSION)
    if ray.version_to_tuple(file_version) >= (0, 8, 0):
        return True

    nodes = content.childNodes()

    for i in range(nodes.count()):
        node = nodes.at(i)
        ct = node.toElement()
        tag_name = ct.tagName()
        if tag_name != 'Client-Template':
            continue

        executable = ct.attribute('executable')
        if not executable:
            continue

        ign_list, unign_list = get_git_default_un_and_ignored(executable)
        if ign_list:
            ct.setAttribute('ignored_extensions', " ".join(ign_list))
        if unign_list:
            ct.setAttribute('unignored_extensions', " ".join(unign_list))

    return True

def rebuild_templates_database(session: 'Session', base: str):        
    # discovery start
    factory = bool(base == 'factory')
    templates_database = session.get_client_templates_database(base)
    templates_database.clear()
    
    template_names = set()
    
    from_desktop_execs = list[NsmDesktopExec]()
    if base == 'factory':
        from_desktop_execs = _get_nsm_capable_execs_from_desktop_files()

    search_paths = _get_search_template_dirs(factory)
    file_rewritten = False

    for search_path in search_paths:
        templates_file = search_path / 'client_templates.xml'
        if not templates_file.is_file():
            continue
        
        if not os.access(templates_file, os.R_OK):
            sys.stderr.write("ray-daemon:No access to %s in %s, ignore it"
                                % (templates_file, search_path))
            continue

        file = open(templates_file, 'r')
        xml = QDomDocument()
        xml.setContent(file.read())
        file.close()

        content = xml.documentElement()

        if content.tagName() != "RAY-CLIENT-TEMPLATES":
            continue

        if not factory:
            # we may rewrite user client templates file
            if content.attribute('VERSION') != ray.VERSION:
                file_rewritten = _rewrite_user_templates_file(
                    content, templates_file)

        erased_by_nsm_desktop_global = bool(
            content.attribute('erased_by_nsm_desktop_file').lower() == 'true')
        
        nodes = content.childNodes()

        for i in range(nodes.count()):
            node = nodes.at(i)
            ct = node.toElement()
            tag_name = ct.tagName()
            if tag_name != 'Client-Template':
                continue

            template_name = ct.attribute('template-name')

            if (not template_name
                    or '/' in template_name
                    or template_name in template_names):
                continue

            executable = ct.attribute('executable')
            protocol = ray.protocol_from_str(ct.attribute('protocol'))
            
            # check if we wan't this template to be erased by a .desktop file
            # with X-NSM-Capable=true
            if ct.attribute('erased_by_nsm_desktop_file'):
                erased_by_nsm_desktop = bool(
                    ct.attribute('erased_by_nsm_desktop_file').lower() == 'true')
            else:
                erased_by_nsm_desktop = erased_by_nsm_desktop_global
            
            nsm_desktop_prior_found = False
            
            # With 'needs_nsm_desktop_file', this template will be provided only if
            # a *.desktop file with the same executable contains X-NSM-Capable=true
            needs_nsm_desktop_file = bool(
                ct.attribute('needs_nsm_desktop_file').lower() == True)

            has_nsm_desktop = False

            # Parse .desktop files in memory
            for fde in from_desktop_execs:
                if fde['executable'] == executable:
                    has_nsm_desktop = True
                    
                    if erased_by_nsm_desktop:
                        # This template won't be provided
                        nsm_desktop_prior_found = True
                    else:
                        # The .desktop file will be skipped,
                        # we use this template instead
                        fde['skipped'] = True
                    break
            else:
                # No *.desktop file with same executable as this template
                if needs_nsm_desktop_file:
                    # This template needs a *.desktop file with X-NSM-Capable
                    # and there is no one, skip this template
                    continue

            if nsm_desktop_prior_found:
                continue

            # check if needed executables are present
            if protocol != ray.Protocol.RAY_NET:
                if not executable:
                    continue

                try_exec_line = ct.attribute('try-exec')
                try_exec_list = try_exec_line.split(';') if try_exec_line else []
                
                if not has_nsm_desktop:
                    try_exec_list.append(executable)

                try_exec_ok = True

                for try_exec in try_exec_list:
                    if not shutil.which(try_exec):
                        try_exec_ok = False
                        break
                
                if not try_exec_ok:
                    continue

            if not has_nsm_desktop:
                # search for '/nsm/server/announce' in executable binary
                # if it is asked by "check_nsm_bin" key
                if ct.attribute('check_nsm_bin') in  ("1", "true"):
                    result = QProcess.execute(
                        'grep', ['-q', '/nsm/server/announce',
                                shutil.which(executable)])
                    if result:
                        continue

                # check if a version is at least required for this template
                # don't use needed-version without check how the program acts !
                needed_version = ct.attribute('needed-version')

                if (needed_version.startswith('.')
                        or needed_version.endswith('.')
                        or not needed_version.replace('.', '').isdigit()):
                    # needed-version not writed correctly, ignores it
                    needed_version = ''

                if needed_version:
                    version_process = QProcess()
                    version_process.start(executable, ['--version'])
                    version_process.waitForFinished(500)

                    # do not allow program --version to be longer than 500ms
                    if version_process.state():
                        version_process.terminate()
                        version_process.waitForFinished(500)
                        continue

                    full_program_version = str(
                        version_process.readAllStandardOutput(),
                        encoding='utf-8')

                    previous_is_digit = False
                    program_version = ''

                    for character in full_program_version:
                        if character.isdigit():
                            program_version += character
                            previous_is_digit = True
                        elif character == '.':
                            if previous_is_digit:
                                program_version += character
                            previous_is_digit = False
                        else:
                            if program_version:
                                break

                    if not program_version:
                        continue

                    neededs = [int(s) for s in needed_version.split('.')]
                    progvss = [int(s) for s in program_version.split('.')]

                    if neededs > progvss:
                        # program is too old, ignore this template
                        continue

            template_client = Client(session)
            template_client.read_xml_properties(ct)
            template_client.client_id = ct.attribute('client_id')
            if not template_client.client_id:
                template_client.client_id == session.generate_abstract_client_id(
                    template_client.executable_path)
            template_client.update_infos_from_desktop_file()
            
            display_name = ''
            if ct.attribute('tp_display_name_is_label') == 'true':
                display_name = template_client.label

            template_names.add(template_name)
            templates_database.append(AppTemplate(
                template_name, template_client, display_name, search_path))
            
            # for Ardour, list ardour templates
            if (base == 'factory'
                    and ct.attribute('list_ardour_templates')
                        in ('true', '1')):
                for ard_tp_path in ardour_templates.list_templates_from_exec(
                        template_client.executable_path):
                    ard_template_client = Client(session)
                    ard_template_client.eat_attributes(template_client)
                    ard_template_client.client_id = template_client.client_id

                    descrip_prefix = _translate(
                        'ardour_tp', 'Session template "%s"') % ard_tp_path.name

                    dsc = descrip_prefix
                    dsc += '.'
                    
                    tp_dsc = ardour_templates.get_description(ard_tp_path)
                    if tp_dsc:
                        dsc += '\n\n'
                        dsc += tp_dsc
                    
                    ard_template_client.description = dsc

                    ard_template_name = f"/ardour_tp/{template_name}/{ard_tp_path.name}"
                    ard_display_name = f"{template_name} -> {ard_tp_path.name}"

                    templates_database.append(AppTemplate(
                        ard_template_name, ard_template_client,
                        ard_display_name, search_path))
                    
    # add fake templates from desktop files
    for fde in from_desktop_execs:
        if fde['skipped']:
            continue

        template_name = '/' + fde['executable']
        display_name = fde['name']

        template_client = Client(session)
        template_client.executable_path = fde['executable']
        template_client.desktop_file = fde['desktop_file']
        template_client.client_id = session.generate_abstract_client_id(
            fde['executable'])
        
        # this client has probably not been tested in RS
        # let it behaves as in NSM
        template_client.prefix_mode = ray.PrefixMode.CLIENT_NAME
        template_client.jack_naming = ray.JackNaming.LONG
        template_client.update_infos_from_desktop_file()
        
        template_names.add(template_name)
        templates_database.append(AppTemplate(
            template_name, template_client, fde['name'], ''))

    if file_rewritten:
        try:
            file = open(templates_file, 'w')
            file.write(xml.toString())
            file.close()
        except:
            sys.stderr.write(
                'unable to rewrite User Client Templates XML File\n')

