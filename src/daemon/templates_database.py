import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Iterator, TypedDict
import logging
import xml.etree.ElementTree as ET
from PyQt5.QtCore import QProcess, QCoreApplication

import xdg
import ray
from daemon_tools import (
    exec_and_desktops,
    TemplateRoots,
    get_git_default_un_and_ignored,
    AppTemplate)
import ardour_templates
from client import Client
from xml_tools import XmlElement

if TYPE_CHECKING:
    from session import Session


_translate = QCoreApplication.translate
_logger = logging.getLogger(__name__)





class NsmDesktopExec(TypedDict):
    executable: str
    name: str
    desktop_file: str
    nsm_capable: bool
    skipped: bool
    

def _get_search_template_dirs(factory: bool) -> list[Path]:
    if factory:
        # search templates in /etc/xdg (RaySession installed)
        templates_root = TemplateRoots.factory_clients_xdg

        # search templates in source code
        if not templates_root.is_dir():
            templates_root = TemplateRoots.factory_clients

        if (templates_root.is_dir()
                and os.access(templates_root, os.R_OK)):
            return sorted([t for t in templates_root.iterdir()])

        return []

    return [TemplateRoots.user_clients]

def _first_desktops_scan() -> list[NsmDesktopExec]:
    desk_paths = [xdg.xdg_data_home()] + xdg.xdg_data_dirs()

    application_dicts = list[NsmDesktopExec]()
    # exec_and_desks = dict[str, str]()
    exec_and_desktops.clear()

    lang = os.getenv('LANG')
    lang_strs = ("[%s]" % lang[0:5], "[%s]" % lang[0:2], "")

    for desk_path in desk_paths:
        full_desk_path = desk_path / 'applications'

        if not full_desk_path.is_dir():
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
                    with open(full_desk_file, 'r') as file:
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
                        exec_and_desktops[executable] = full_desk_file
                    
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

def _should_rewrite_user_templates_file(
        root: ET.Element, templates_file: Path) -> bool:
    if not os.access(templates_file, os.W_OK):
        return False

    xroot = XmlElement(root)
    file_version = xroot.str('VERSION')

    if (ray.version_to_tuple(file_version)
            >= ray.version_to_tuple(ray.VERSION)):
        return False

    xroot.set_str('VERSION', ray.VERSION)
    root.attrib['VERSION'] = ray.VERSION
    if ray.version_to_tuple(file_version) >= (0, 8, 0):
        return True

    for child in root:
        if child.tag != 'Client-Template':
            continue

        executable = XmlElement(child).str('executable')
        if not executable:
            continue

        ign_list, unign_list = get_git_default_un_and_ignored(executable)
        if ign_list:
            child.attrib['ignored_extensions'] = " ".join(ign_list)
        if unign_list:
            child.attrib['unignored_extensions'] = " ".join(unign_list)

    return True

def _list_xml_elements(base: str) -> Iterator[tuple[Path, XmlElement]]:
    factory = bool(base == 'factory')
    search_paths = _get_search_template_dirs(factory)
    
    for search_path in search_paths:
        file_rewritten = False
        templates_file = search_path / 'client_templates.xml'
        if not templates_file.is_file():
            continue
        
        if not os.access(templates_file, os.R_OK):
            _logger.error(
                f"No access to {templates_file} in {search_path}, ignore it")
            continue
        
        try:
            tree = ET.parse(templates_file)
        except:
            _logger.error(f"{templates_file} is not a valid xml file")
            continue

        root = tree.getroot()
        if root.tag != 'RAY-CLIENT-TEMPLATES':
            continue
        
        if not factory and root.attrib.get('VERSION') != ray.VERSION:
            # we may rewrite user client templates file
            file_rewritten = _should_rewrite_user_templates_file(
                root, templates_file)
        
        xroot = XmlElement(root)
        erased_by_nsm_desktop_global = xroot.bool('erased_by_nsm_desktop_file')

        for c in xroot.iter():
        # for child in root:
            if c.el.tag != 'Client-Template':
                continue
            
            if (erased_by_nsm_desktop_global
                    and not c.bool('erased_by_nsm_desktop_file')):
                c.set_bool('erased_by_nsm_desktop_file', True)
                
            yield search_path, c

        if file_rewritten:
            _logger.info('rewrite user client templates XML file')
            try:
                tree.write(templates_file)
            except:
                _logger.error(
                    'Rewrite user client templates XML file failed')

def rebuild_templates_database(session: 'Session', base: str):        
    # discovery start
    templates_database = session.get_client_templates_database(base)
    templates_database.clear()
    
    template_names = set[str]()
    template_execs = set[str]()
    
    for search_path, c in _list_xml_elements(base):
        template_execs.add(c.str('executable'))

    from_desktop_execs = list[NsmDesktopExec]()
    if base == 'factory':
        from_desktop_execs = _first_desktops_scan()

    for search_path, c in _list_xml_elements(base):
        template_name = c.str('template-name')

        if (not template_name
                or '/' in template_name
                or template_name in template_names):
            continue

        executable = c.str('executable')
        protocol = ray.protocol_from_str(c.str('protocol'))

        # check if we wan't this template to be erased by a .desktop file
        # with X-NSM-Capable=true
        erased_by_nsm_desktop = c.bool('erased_by_nsm_desktop')
        
        nsm_desktop_prior_found = False
        
        # With 'needs_nsm_desktop_file', this template will be provided only if
        # a *.desktop file with the same executable contains X-NSM-Capable=true
        needs_nsm_desktop_file = c.bool('needs_nsm_desktop_file')
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
            
            try_exec_line = c.str('try-exec')
            try_exec_list = try_exec_line.split(';') if try_exec_line else []
            
            if not has_nsm_desktop:
                try_exec_list.append(executable)

            try_exec_ok = True

            for try_exec in try_exec_list:
                if not try_exec:
                    continue
                
                if not shutil.which(try_exec):
                    try_exec_ok = False
                    break
            
            if not try_exec_ok:
                continue

        if not has_nsm_desktop:
            # search for '/nsm/server/announce' in executable binary
            # if it is asked by "check_nsm_bin" key
            if c.bool('check_nsm_bin'):
                result = QProcess.execute(
                    'grep', ['-q', '/nsm/server/announce',
                             shutil.which(executable)])
                if result:
                    continue

            # check if a version is at least required for this template
            # don't use needed-version without check how the program acts !
            needed_version = c.str('needed-version')

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
        template_client.read_xml_properties(c)
        template_client.client_id = c.str('client_id')        
        if not template_client.client_id:
            template_client.client_id == session.generate_abstract_client_id(
                template_client.executable_path)
        template_client.update_infos_from_desktop_file()
        
        display_name = ''
        if c.bool('tp_display_name_is_label'):
            display_name = template_client.label

        template_names.add(template_name)
        templates_database.append(AppTemplate(
            template_name, template_client, display_name, search_path))
        
        # for Ardour, list ardour templates
        if base == 'factory' and c.bool('list_ardour_templates'):
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
            template_name, template_client, fde['name'], Path()))


