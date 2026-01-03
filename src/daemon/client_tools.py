import logging
from pathlib import Path
import os
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

import ray

from daemon_tools import TemplateRoots

if TYPE_CHECKING:
    from client import Client


_logger = logging.getLogger(__name__)


def rename_client_files(
        client: 'Client', spath: Path,
        old_session_name: str, new_session_name: str,
        old_prefix: str, new_prefix: str,
        old_client_id: str, new_client_id: str,
        old_client_links_dir: str, new_client_links_dir: str):

    # rename client script dir
    scripts_dir = spath / f'{ray.SCRIPTS_DIR}.{old_client_id}'
    if os.access(scripts_dir, os.W_OK) and old_client_id != new_client_id:
        scripts_dir = scripts_dir.rename(f'{ray.SCRIPTS_DIR}.{new_client_id}')

    project_path = spath / f'{old_prefix}.{old_client_id}'

    files_to_rename = list[tuple[Path, Path]]()
    do_rename = True

    if client.is_ray_hack:
        if project_path.is_dir():
            if not os.access(project_path, os.W_OK):
                do_rename = False
            else:
                os.environ['RAY_SESSION_NAME'] = old_session_name
                os.environ['RAY_CLIENT_ID'] = old_client_id
                pre_config_file = os.path.expandvars(
                    client.ray_hack.config_file)

                os.environ['RAY_SESSION_NAME'] = new_session_name
                os.environ['RAY_CLIENT_ID'] = new_client_id
                post_config_file = os.path.expandvars(
                    client.ray_hack.config_file)

                os.unsetenv('RAY_SESSION_NAME')
                os.unsetenv('RAY_CLIENT_ID')

                full_pre_config_file = project_path / pre_config_file
                full_post_config_file = project_path / post_config_file

                if full_pre_config_file.exists():
                    files_to_rename.append((full_pre_config_file,
                                            full_post_config_file))

                files_to_rename.append(
                    (project_path, spath / f"{new_prefix}.{new_client_id}"))
    else:
        for file_path in spath.iterdir():
            if file_path.name.startswith(f"{old_prefix}.{old_client_id}."):
                if not os.access(file_path, os.W_OK):
                    do_rename = False
                    break

                endfile = file_path.name.replace(
                    f"{old_prefix}.{old_client_id}.", '', 1)

                next_path = spath / f"{new_prefix}.{new_client_id}.{endfile}"

                if next_path != file_path:
                    if next_path.exists():
                        do_rename = False
                        break
                    
                    files_to_rename.append((file_path, next_path))

            elif file_path.name == f"{old_prefix}.{old_client_id}":
                if not os.access(file_path, os.W_OK):
                    do_rename = False
                    break

                next_path = spath / f"{new_prefix}.{new_client_id}"
                
                if next_path.exists():
                    do_rename = False
                    break

                # only for hydrogen
                hydrogen_file = (
                    project_path / f"{old_prefix}.{old_client_id}.h2song")
                hydrogen_autosave = (
                    project_path / f"{old_prefix}.{old_client_id}.autosave.h2song")

                if hydrogen_file.is_file() and os.access(hydrogen_file, os.W_OK):
                    new_hydro_file = (
                        project_path / f"{new_prefix}.{new_client_id}.h2song")
                    
                    if new_hydro_file != hydrogen_file:
                        if new_hydro_file.exists():
                            do_rename = False
                            break

                        files_to_rename.append((hydrogen_file, new_hydro_file))

                if (hydrogen_autosave.is_file()
                        and os.access(hydrogen_autosave, os.W_OK)):
                    new_hydro_autosave = (
                        project_path
                        / f"{new_prefix}.{new_client_id}.autosave.h2song")

                    if new_hydro_autosave != hydrogen_autosave:
                        if new_hydro_autosave.exists():
                            do_rename = False
                            break

                        files_to_rename.append((hydrogen_autosave, new_hydro_autosave))

                # only for ardour
                ardour_file = project_path / f"{old_prefix}.ardour"
                ardour_bak = project_path / f"{old_prefix}.ardour.bak"
                ardour_audio = project_path / 'interchange' / project_path.name

                if ardour_file.is_file() and os.access(ardour_file, os.W_OK):
                    new_ardour_file = project_path / f"{new_prefix}.ardour"
                    if new_ardour_file != ardour_file:
                        if new_ardour_file.exists():
                            do_rename = False
                            break

                        files_to_rename.append((ardour_file, new_ardour_file))

                        # change ardour session name
                        try:
                            tree = ET.parse(ardour_file)
                            root = tree.getroot()
                            if root.tag == 'Session':
                                root.attrib['name'] = new_prefix

                            # write the file
                            ET.indent(tree, level=0)
                            tree.write(ardour_file)

                        except:
                            _logger.warning(
                                'Failed to change ardour session '
                                f'name to "{new_prefix}"')

                if ardour_bak.is_file() and os.access(ardour_bak, os.W_OK):
                    new_ardour_bak = project_path / f"{new_prefix}.ardour.bak"
                    if new_ardour_bak != ardour_bak:
                        if new_ardour_bak.exists():
                            do_rename = False
                            break

                        files_to_rename.append((ardour_bak, new_ardour_bak))

                if ardour_audio.is_dir() and os.access(ardour_audio, os.W_OK):
                    new_ardour_audio = (
                        project_path / 'interchange' / f"{new_prefix}.{new_client_id}")
                    
                    if new_ardour_audio != ardour_audio:
                        if new_ardour_audio.exists():
                            do_rename = False
                            break

                        files_to_rename.append((ardour_audio, new_ardour_audio))

                # for Vee One Suite
                for extfile in ('samplv1', 'synthv1', 'padthv1', 'drumkv1'):
                    old_veeone_file = project_path / f"{old_session_name}.{extfile}"
                    new_veeone_file = project_path / f"{new_session_name}.{extfile}"
                    if new_veeone_file == old_veeone_file:
                        continue

                    if (old_veeone_file.is_file()
                            and os.access(old_veeone_file, os.W_OK)):
                        if new_veeone_file.exists():
                            do_rename = False
                            break

                        files_to_rename.append((old_veeone_file,
                                                new_veeone_file))

                files_to_rename.append((spath / file_path, next_path))                    

            elif file_path.name == old_client_links_dir:
                # this section only concerns Carla links dir
                # used to save links for convolutions files or soundfonts
                # or any other linked resource.
                if old_client_links_dir == new_client_links_dir:
                    continue

                if not file_path.is_dir():
                    continue
                
                if not os.access(file_path, os.W_OK):
                    do_rename = False
                    break

                full_new_links_dir = spath / new_client_links_dir
                if full_new_links_dir.exists():
                    do_rename = False
                    break

                files_to_rename.append((file_path, full_new_links_dir))

    if not do_rename:
        client.prefix_mode = ray.PrefixMode.CUSTOM
        client.custom_prefix = old_prefix
        _logger.warning(
            f"daemon choose to not rename files for client_id {client.client_id}")
        # it should not be a client_id problem here
        return

    # change last_used snapshot of ardour
    instant_file = project_path / 'instant.xml'
    if instant_file.is_file() and os.access(instant_file, os.W_OK):
        try:
            tree = ET.parse(instant_file)
            root = tree.getroot()
            if root.tag == 'instant':
                for child in root:
                    if child.tag == 'LastUsedSnapshot':
                        if child.attrib.get('name') == old_prefix:
                            child.attrib['name'] = new_prefix
                        break
            
            ET.indent(tree, level=0)
            tree.write(instant_file)
            
        except:
            _logger.warning(
                f'Failed to change Ardour LastUsedSnapshot in {instant_file}')

    for now_path, next_path in files_to_rename:
        _logger.info(f'renaming\n\tfile: {now_path}\n\tto:   {next_path}')
        os.rename(now_path, next_path)
        
def adjust_files_after_copy(
        client: 'Client', new_session_full_name: str,
        template_save=ray.Template.NONE):
    spath = client.session.path
    old_session_name = client.session.name
    new_session_name = Path(new_session_full_name).name
    new_client_id = client.client_id
    old_client_id = client.client_id
    new_client_links_dir = client.links_dirname
    old_client_links_dir = new_client_links_dir

    X_SESSION_X = "XXX_SESSION_NAME_XXX"
    X_CLIENT_ID_X = "XXX_CLIENT_ID_XXX"
    X_CLIENT_LINKS_DIR_X = "XXX_CLIENT_LINKS_DIR_XXX"
    'used for Carla links dir'

    match template_save:
        case ray.Template.NONE:
            spath = client.session.root / new_session_full_name

        case ray.Template.RENAME:
            ...

        case ray.Template.SESSION_SAVE:
            spath = Path(new_session_full_name)
            if not spath.is_absolute():
                spath = TemplateRoots.user_sessions / new_session_full_name
            new_session_name = X_SESSION_X

        case ray.Template.SESSION_SAVE_NET:
            spath = (client.session.root
                        / TemplateRoots.net_session_name
                        / new_session_full_name)
            new_session_name = X_SESSION_X

        case ray.Template.SESSION_LOAD:
            spath = client.session.root / new_session_full_name
            old_session_name = X_SESSION_X

        case ray.Template.SESSION_LOAD_NET:
            spath = client.session.root / new_session_full_name
            old_session_name = X_SESSION_X

        case ray.Template.CLIENT_SAVE:
            spath = TemplateRoots.user_clients / new_session_full_name
            new_session_name = X_SESSION_X
            new_client_id = X_CLIENT_ID_X
            new_client_links_dir = X_CLIENT_LINKS_DIR_X

        case ray.Template.CLIENT_LOAD:
            spath = client.session.path
            old_session_name = X_SESSION_X
            old_client_id = X_CLIENT_ID_X
            old_client_links_dir = X_CLIENT_LINKS_DIR_X

    if spath is None:
        _logger.error(
            f'Impossible to adjust files after copy '
            f'for client {client.client_id} : '
            f'spath is None')
        return

    old_prefix = old_session_name
    new_prefix = new_session_name
    
    match client.prefix_mode:
        case ray.PrefixMode.CLIENT_NAME:
            old_prefix = new_prefix = client.name
        case ray.PrefixMode.CUSTOM:
            old_prefix = new_prefix = client.custom_prefix

    rename_client_files(
        client, spath,
        old_session_name, new_session_name,
        old_prefix, new_prefix,
        old_client_id, new_client_id,
        old_client_links_dir, new_client_links_dir)