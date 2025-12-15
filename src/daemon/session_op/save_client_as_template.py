import logging
import os
import shutil
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

from qtpy.QtCore import QCoreApplication
from osclib.bases import OscPack

import ray
from osclib import Address
import osc_paths.ray as r
from xml_tools import XmlElement

from client import Client
from daemon_tools import highlight_text, TemplateRoots

from .session_op import SessionOp

if TYPE_CHECKING:
    from session_operating import OperatingSession


_logger = logging.getLogger(__name__)
_translate = QCoreApplication.translate


class SaveClientAsTemplate(SessionOp):
    def __init__(self, session: 'OperatingSession',
                 client: Client, template_name: str,
                 osp: OscPack | None =None):
        super().__init__(session, osp)
        self.client = client
        self.template_name = template_name
        self.routine = [self.copy_client_to_template,
                        self.adjust_files]

    def copy_client_to_template(self):
        session = self.session
        client = self.client

        template_dir = TemplateRoots.user_clients / self.template_name
        if template_dir.exists():
            try:
                shutil.rmtree(template_dir)
            except:
                self.error(
                    ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'impossible to remove %s !')
                        % highlight_text(template_dir))
                return

        template_dir.mkdir(parents=True)

        if client.is_ray_net:
            if client.ray_net.daemon_url:
                client.ray_net.session_template = self.template_name
                net_session_root = client.ray_net.session_root
                if client.is_running:
                    net_session_root = client.ray_net.running_session_root

                session.send(
                    Address(client.ray_net.daemon_url),
                    r.server.SAVE_SESSION_TEMPLATE,
                    session.name,
                    self.template_name,
                    net_session_root)

        # copy files
        client_files = client.project_files

        if client_files:
            client.set_status(ray.ClientStatus.COPY)
            err = session.file_copier.start_client_copy(
                client.client_id, client_files, template_dir)
            if err is not ray.Err.OK:
                client.set_status(client.status)
                self.error(
                    err,
                    _translate('error',
                               'Failed to save client as template'))
                return
            
        self.next(ray.WaitFor.FILE_COPY)

    def adjust_files(self):
        session = self.session
        client = self.client
        client.set_status(client.status) # see set_status to see why
        
        if session.file_copier.aborted:
            self.error(
                ray.Err.COPY_ABORTED,
                _translate('error', 'No template created, copy was aborted'))
            return

        if client.prefix_mode is not ray.PrefixMode.CUSTOM:
            client.adjust_files_after_copy(
                self.template_name, ray.Template.CLIENT_SAVE)

        user_clients_path = TemplateRoots.user_clients
        xml_file = user_clients_path / 'client_templates.xml'

        # security check
        if xml_file.exists():
            if not os.access(xml_file, os.W_OK):
                self.error(
                    ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', '%s is not writeable !') % xml_file)
                return

            if xml_file.is_dir():
                # should not be a dir, remove it !
                _logger.info(
                    f'removing {xml_file} because it is a dir, '
                    'it must be a file')
                try:
                    shutil.rmtree(xml_file)
                except:
                    self.error(
                        ray.Err.CREATE_FAILED,
                        _translate('GUIMSG', 'Failed to remove %s directory !')
                            % xml_file)
                    return

        if not user_clients_path.is_dir():
            try:
                user_clients_path.mkdir(parents=True)
            except BaseException as e:
                _logger.error(str(e))
                self.error(
                    ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'Failed to create directories for %s')
                        % user_clients_path)
                return

        # create client_templates.xml if it does not exists
        if not xml_file.is_file():
            root = ET.Element('RAY-CLIENT-TEMPLATES')
            tree = ET.ElementTree(root)
            try:
                tree.write(xml_file)
            except:
                _logger.error(
                    'Failed to create user client templates xml file')
                self.error(
                    ray.Err.CREATE_FAILED,
                    _translate('GUIMSG', 'Failed to write xml file  %s')
                        % str(xml_file))
                return

        try:
            tree = ET.parse(xml_file)
        except BaseException as e:
            _logger.error(str(e))
            self.error(
                ray.Err.CREATE_FAILED,
                _translate('GUIMSG', '%s seems to not be a valid XML file.')
                    % str(xml_file))
            return

        root = tree.getroot()
        
        if root.tag != 'RAY-CLIENT-TEMPLATES':
            self.error(
                ray.Err.CREATE_FAILED,
                _translate('GUIMSG', '%s is not a client templates XML file.')
                    % str(xml_file))
            return
        
        # remove the existant templates with the same name
        to_rm_childs = list[ET.Element]()
        for child in root:
            if child.tag != 'Client-Template':
                continue
            
            c = XmlElement(child)
            if c.string('template-name') == self.template_name:
                to_rm_childs.append(child)
                
        for child in to_rm_childs:
            root.remove(child)

        # create the client template item in xml file
        c = XmlElement(ET.SubElement(root, 'Client-Template'))
        client.write_xml_properties(c)
        c.set_str('template-name', self.template_name)
        c.set_str('client_id', client.short_client_id(client.client_id))
        
        if not client.is_running:
            c.set_bool('launched', False)
        
        # write the file
        ET.indent(tree, level=0)
        
        try:
            tree.write(xml_file)
        except Exception as e:
            _logger.error(str(e))
            self.error(
                ray.Err.CREATE_FAILED,
                _translate('GUIMSG', 'Failed to write XML file %s.')
                    % str(xml_file))
            return

        client.template_origin = self.template_name
        client.send_gui_client_properties()

        template_data_base_users = \
            session.get_client_templates_database('user')
        template_data_base_users.clear()

        session.send_gui_message(
            _translate('message', 'Client template %s created')
                % self.template_name)

        self.reply('client template created')
