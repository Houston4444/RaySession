
# Imports from standard library
import os
from pathlib import Path
from re import template
import shutil
from typing import TYPE_CHECKING, Iterator, TypedDict
import logging
import xml.etree.ElementTree as ET

# third party imports
from qtpy.QtCore import QProcess, QCoreApplication
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

# Imports from src/shared
import ray
import xdg
from xml_tools import XmlElement
import osc_paths.nsm as nsm

# Local imports
from daemon_tools import (
    exec_and_desktops,
    TemplateRoots,
    get_git_default_un_and_ignored,
    AppTemplate)
import ardour_templates
from client import Client

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


class YamxlElement:
    def __init__(self, element: XmlElement | CommentedMap):
        self.el = element
    
    def string(self, key: str, default='') -> str:
        if isinstance(self.el, CommentedMap):
            return str(self.el.get(key, default=default))        
        return self.el.string(key, default=default)

    def bool(self, key: str, default=False) -> bool:
        if isinstance(self.el, CommentedMap):
            return bool(self.el.get(key, default=default))
        return self.el.bool(key, default=default)


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

    lang = os.getenv('LANG', '')
    if len(lang) < 5:
        lang_strs = (lang, lang, '')
    else:
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
    file_version = xroot.string('VERSION')

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

        executable = XmlElement(child).string('executable')
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
        except BaseException as e:
            _logger.error(
                f"{templates_file} is not a valid xml file\n{str(e)}")
            continue

        root = tree.getroot()
        if root.tag != 'RAY-CLIENT-TEMPLATES':
            continue
        
        if not factory and root.attrib.get('VERSION') != ray.VERSION:
            # we may rewrite user client templates file
            file_rewritten = _should_rewrite_user_templates_file(
                root, templates_file)
        
        xroot = XmlElement(root)
        erased_by_nsm_desktop_global = xroot.bool(
            'erased_by_nsm_desktop_file')

        for c in xroot.iter():
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

def _process_element(
        template_name: str, c: YamxlElement,
        from_desktop_execs:list[NsmDesktopExec], session: 'Session',
        template_names: set[str], templates_database: list[AppTemplate],
        search_path: Path, base: str):
    executable = c.string('executable')
    protocol = ray.Protocol.from_string(c.string('protocol'))

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
            return

    if nsm_desktop_prior_found:
        return

    # check if needed executables are present
    if protocol is not ray.Protocol.RAY_NET:
        if not executable:
            return
        
        try_exec_line = c.string('try-exec')
        try_execs = try_exec_line.split(';') if try_exec_line else []
        
        if not has_nsm_desktop:
            try_execs.append(executable)

        try_exec_ok = True

        for try_exec in try_execs:
            if not try_exec:
                continue
            
            if not shutil.which(try_exec):
                try_exec_ok = False
                break
        
        if not try_exec_ok:
            return

    if not has_nsm_desktop:
        # search for nsm.server.ANNOUNCE in executable binary
        # if it is asked by "check_nsm_bin" key
        if c.bool('check_nsm_bin'):
            which_exec = shutil.which(executable)
            if which_exec:
                result = QProcess.execute(
                    'grep', ['-q', nsm.server.ANNOUNCE,
                            which_exec])
                if result:
                    return

        # check if a version is at least required for this template
        # don't use needed-version without check how the program acts !
        needed_version = c.string('needed-version')

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
            if version_process.state() != QProcess.ProcessState.NotRunning:
                version_process.terminate()
                version_process.waitForFinished(500)
                return

            full_program_version = str(
                version_process.readAllStandardOutput(), # type:ignore
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
                return

            neededs = [int(s) for s in needed_version.split('.')]
            progvss = [int(s) for s in program_version.split('.')]

            if neededs > progvss:
                # program is too old, ignore this template
                return

    template_client = Client(session)
    if isinstance(c.el, CommentedMap):
        template_client.read_yaml_properties(c.el)
    else:
        template_client.read_xml_properties(c.el)

    template_client.client_id = c.string('client_id')        
    if not template_client.client_id:
        template_client.client_id = session.generate_abstract_client_id(
            template_client.executable)
    template_client.update_infos_from_desktop_file()
    
    display_name = ''
    if c.bool('tp_display_name_is_label'):
        display_name = template_client.label

    _logger.info(f'Client template "{template_name}" found.')
    template_names.add(template_name)
    templates_database.append(AppTemplate(
        template_name, template_client, display_name, search_path))
    
    # for Ardour, list ardour templates
    if base == 'factory' and c.bool('list_ardour_templates'):
        for ard_tp_path in ardour_templates.list_templates_from_exec(
                template_client.executable):
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

            ard_template_name = \
                f"/ardour_tp/{template_name}/{ard_tp_path.name}"
            ard_display_name = f"{template_name} -> {ard_tp_path.name}"

            templates_database.append(AppTemplate(
                ard_template_name, ard_template_client,
                ard_display_name, search_path))

def rebuild_templates_database(session: 'Session', base: str):
    # discovery start
    templates_database = session.get_client_templates_database(base)
    templates_database.clear()
    
    template_names = set[str]()
    from_desktop_execs = list[NsmDesktopExec]()
    factory = bool(base == 'factory')
    if factory:
        from_desktop_execs = _first_desktops_scan()
    
    yaml = YAML()
    
    _logger.info(f'Search {base} client template')
    
    search_paths = _get_search_template_dirs(factory)
    for search_path in search_paths:
        _logger.debug(f'search client templates in {search_path}')

        # first parse all folders in search path,
        # if the folder contains ray_client_template.yaml, then it is
        # a client template.
        for template_dir in search_path.iterdir():
            t_yaml_file = template_dir / 'ray_client_template.yaml'
            if not t_yaml_file.is_file():
                continue

            template_name = template_dir.name
            if template_name in template_names:
                _logger.debug(f'"{template_name}" skipped, it already exists')
                continue
            
            try:
                with open(t_yaml_file, 'r') as f:
                    t_map = yaml.load(f)
                    assert isinstance(t_map, CommentedMap)
            except BaseException as e:
                _logger.error(
                    f'Fail to read {t_yaml_file} as a yaml file,\n'
                    f'{str(e)}')
                continue
            
            yamxl = YamxlElement(t_map)
            app = yamxl.string('app')
            version = yamxl.string('version')
            
            if app.upper() != 'RAY-CLIENT-TEMPLATE':
                continue

            _logger.debug(f'check "{template_name}" from {t_yaml_file}')
            _process_element(template_name, yamxl, from_desktop_execs,
                             session, template_names, templates_database,
                             search_path, base)

        # look if there is a global client_templates.yaml file directly
        # in search path, and parse clietn templates from it
        glob_yaml_file = search_path / 'client_templates.yaml'
        if glob_yaml_file.is_file():        
            try:
                with open(glob_yaml_file, 'r') as f:
                    ts_map = yaml.load(glob_yaml_file)
                    assert isinstance(ts_map, CommentedMap)
            except BaseException as e:
                _logger.error(
                    f'Fail to read {glob_yaml_file} as a yaml file,\n'
                    f'{str(e)}')
                continue
            
            app = str(ts_map.get('app', ''))
            version = str(ts_map.get('version'))
            if app.upper() != 'RAY-CLIENT-TEMPLATES':
                continue
            
            templates = ts_map.get('templates')
            if not isinstance(templates, CommentedMap):
                continue
            
            for template_name, t_map in templates:
                if not template_name or '/' in template_name:
                    continue            
                if not isinstance(t_map, CommentedMap):
                    continue
                _logger.debug(
                    f'check "{template_name}" from {glob_yaml_file}')
                _process_element(template_name, YamxlElement(t_map),
                                from_desktop_execs, session, template_names,
                                templates_database, search_path, base)
            continue

        # process XML file if it exists and if yaml file does not exists
        xml_rewritten = False
        xml_templates_file = search_path / 'client_templates.xml'
        if not xml_templates_file.is_file():
            continue
        
        if not os.access(xml_templates_file, os.R_OK):
            _logger.error(
                f'No access to {xml_templates_file} in {search_path}, '
                'ignore it')
            continue
        
        try:
            tree = ET.parse(xml_templates_file)
        except BaseException as e:
            _logger.error(
                f"{xml_templates_file} is not a valid xml file\n{str(e)}")
            continue

        root = tree.getroot()
        if root.tag != 'RAY-CLIENT-TEMPLATES':
            continue
        
        if not factory and root.attrib.get('VERSION') != ray.VERSION:
            # we may rewrite user client templates file
            xml_rewritten = _should_rewrite_user_templates_file(
                root, xml_templates_file)
        
        xroot = XmlElement(root)
        erased_by_nsm_desktop_global = xroot.bool(
            'erased_by_nsm_desktop_file')

        for c in xroot.iter():
            if c.el.tag != 'Client-Template':
                continue
            
            if (erased_by_nsm_desktop_global
                    and not c.bool('erased_by_nsm_desktop_file')):
                c.set_bool('erased_by_nsm_desktop_file', True)
            
            template_name = c.string('template-name')
            _logger.debug(
                f'check "{template_name}" from {xml_templates_file}')
            _process_element(
                template_name, YamxlElement(c),
                from_desktop_execs, session, template_names,
            templates_database, search_path, base)

        if xml_rewritten:
            _logger.info('rewrite user client templates XML file')
            try:
                tree.write(xml_templates_file)
            except:
                _logger.error(
                    'Rewrite user client templates XML file failed')
                    
    # add fake templates from desktop files
    for fde in from_desktop_execs:
        if fde['skipped']:
            continue

        template_name = '/' + fde['executable']
        display_name = fde['name']

        template_client = Client(session)
        template_client.executable = fde['executable']
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


