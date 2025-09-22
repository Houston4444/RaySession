from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import LineCol

file = Path('/home/houstonlzk5/Ray Sessions/tests/pokpprotl/JACK Connections.patch.yaml')
file2 = file.parent / 'JACK Connections.patchtest.yaml'
yaml = YAML()
docu = yaml.load(file)
print('docu uss', type(docu), isinstance(docu, dict))
print('ouji', docu['scenarios'][0]['name'])
print('linerow', docu['scenarios'][0].lc.data['name'])
    
    


outi = yaml.dump(docu, file2)
# with open(file2, 'w') as f:
#     f.write(outi)