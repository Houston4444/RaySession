from pathlib import Path
import sys
import xml.etree.ElementTree as ET


sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))
sys.path.insert(1, str(Path(__file__).parents[2] / 'HoustonPatchbay/source'))

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from xml_tools import XmlElement

from daemon_tools import TemplateRoots
from client import Client
from session_dummy import DummySession

yaml = YAML()
base_path = TemplateRoots.factory_clients
sess = DummySession(Path.home() / 'RayS Sessons')

for tdir in base_path.iterdir():
    xml_file = tdir / 'client_templates.xml'
    if not xml_file.is_file():
        continue
    
    map = {}
    tree = ET.parse(xml_file)
    root = tree.getroot()
    print('pzae', xml_file, root.tag)
    for child in root:
        if child.tag != 'Client-Template':
            continue
    
        template_name = child.get('template-name')
        if not template_name:
            print('problème, pas de name')
            continue
        xchild = XmlElement(child)
        this = map[template_name] = CommentedMap()
        client = Client(sess)
        client.read_xml_properties(xchild)
        client.write_yaml_properties(this, for_template=True)
        for key in 'name', 'desktop_file':
            if key in this:
                this.pop(key)
    
        desktop_file = xchild.string('desktop_file')
        if desktop_file:
            this['desktop_file'] = desktop_file

        for key in ('erased_by_nsm_desktop', 'needs_nsm_desktop_file',
                    'check_nsm_bin', 'tp_display_name_is_label',
                    'list_ardour_templates'):
            if xchild.bool(key):
                this[key] = True
    
        for key in 'try-exec', 'needed-version':
            value_str = xchild.string(key)
            if value_str:
                this[key] = value_str
    
        client_id = child.get('client_id')
        if client_id is not None:
            this['client_id'] = client_id
    
    glob_map = {}
    glob_map['app'] = 'RAY-CLIENT-TEMPLATES'
    glob_map['version'] = '0.18.0'
    glob_map['templates'] = map
    yaml_file = tdir / 'client_templates.yaml'
    with open(yaml_file, 'w') as f:
        yaml.dump(glob_map, f)