
from typing import Iterator, Optional
from pathlib import Path
import shutil
import logging
import xml.etree.ElementTree as ET


_logger = logging.getLogger()


def list_templates(templates_path: Path) -> Iterator[Path]:
    if not templates_path.is_dir():
        return
    
    for path in templates_path.iterdir():
        if path.is_dir():
            tp_file = path / f'{path.name}.template'
            if tp_file.is_file():
                yield path

def get_template_path_from_name(
        template_name: str, executable: str) -> Optional[Path]:
    templates_dir = get_templates_dir(executable)
    if templates_dir is None:
        return None
    return templates_dir / template_name

def get_templates_dir(executable: str) -> Optional[Path]:
    if executable.lower().startswith('ardour'):
        ard_version = get_executable_version(executable)
        if ard_version is None:
            return None
        
        return Path.home() / '.config' / f'ardour{ard_version}' / 'templates'
    
    if executable.lower().startswith('mixbus'):
        base_exe = executable.rpartition('/')[2]
        
        return Path.home() / '.config' / base_exe.lower() / 'templates'
    
    return None

def get_description(template_path: Path) -> str:
    tp_file_path = template_path / f'{template_path.name}.template'
    
    try:
        tree = ET.parse(tp_file_path)
    except BaseException as e:
        _logger.warning(f"Failed to read template description from {tp_file_path}")
        _logger.warning(str(e))
        return ''
    
    root = tree.getroot()
    if root.tag != 'Session':
        _logger.warning(f'{tp_file_path} is not an ardour session template.')
        return ''

    for child in root:
        if child.tag == 'description':
            return child.text
        
    return ''

def get_executable_version(executable: str) -> Optional[int]:
    full_exec = shutil.which(executable)
    if full_exec is None:
        return None

    exec_path = Path(full_exec)
    low_name = exec_path.name.lower()
    if not low_name:
        return None
    
    version_str = ''
    while low_name[-1].isdigit():
        version_str = low_name[-1] + version_str
        low_name = low_name[:-1]
        
    if low_name in ('ardour', 'mixbus') and version_str:
        return int(version_str)

    with open(exec_path, 'r') as f:
        contents = f.read(65536)
        for line in contents.splitlines():
            if line.strip().startswith('exec '):
                for string in line.split('/'):
                    if string.startswith('ardour') and string[6:].isdigit():
                        return int(string[6:])
    
    return None

def list_templates_from_exec(executable: str) -> Iterator[Path]:
    templates_path = get_templates_dir(executable)
    if templates_path:
        for tp_name in list_templates(templates_path):
            yield tp_name

def copy_template_to_session(template: Path, session_path: Path,
                             ardour_sess_name: str,
                             client_id: str) -> bool:
    def _remove_copied_dir(copied_path: Path):
        '''executed at end if copy and rename fails'''
        if not copied_path.exists():
            return
        
        try:
            shutil.rmtree(copied_path)
        except:
            _logger.warning(f"Failed to remove copied path {copied_path}")
    
    next_path = session_path / f"{ardour_sess_name}.{client_id}"
    if next_path.exists():
        _logger.warning(
            f"Can't copy Ardour template, {next_path} already exists")
        return False
    
    try:
        shutil.copytree(template, next_path)
    except BaseException as e:
        _logger.error("Failed to copy Ardour template")
        _logger.error(str(e))
        _remove_copied_dir(next_path)       
        return False
    
    tp_file_path = next_path / f"{template.name}.template"
    if not tp_file_path.exists():
        _logger.error(f"{template.name}.template does not exists after copy !")
        _remove_copied_dir(next_path)
        return False

    try:
        tp_file_path.rename(tp_file_path.parent / f"{ardour_sess_name}.ardour")
    except BaseException as e:
        _logger.error(
            f"Failed to rename {template.name}.template to {ardour_sess_name}.ardour")
        _logger.error(str(e))
        _remove_copied_dir(next_path)
        return False

    return True