# splitted versus monolitic client_template yaml file parsing
from pathlib import Path
from ruamel.yaml import YAML
import time

def read_from_split(base_dir: Path):
    globimap = {}
    for dir in base_dir.iterdir():
        yaml_file = dir / 'toto.yaml'
        if yaml_file.exists():
            with open(yaml_file, 'r') as f:
                globimap[dir.name] = yaml.load(f)
                
    return globimap

def read_from_mono(base_dir: Path):
    glob_yaml_file = base_dir / 'toutou.yaml'
    with open(glob_yaml_file, 'r') as f:
        globimap = yaml.load(glob_yaml_file)
    
    return globimap
    
yaml = YAML()

base_dir = Path.home() / 'yaml_mono'
start = time.time()
globisplit = read_from_split(base_dir)
done_0 = time.time()
globimono = read_from_mono(base_dir)
done_1 = time.time()

print('split', done_0 - start, 'mono', done_1 - done_0)
print(globisplit)

print('\n\n ----- MONO  ------')

print(globimono)


# base_dir.mkdir(exist_ok=True)

# globimap = {}

# for i in range(20):
#     folder = base_dir / f'folder_{i}'
#     folder.mkdir(exist_ok=True)
#     yaml_file = folder / 'toto.yaml'
#     map = {'chocho': i * i - 20, 'terenepa': 'souliba', 'cholou': 'Sephoa'}
#     with open(yaml_file, 'w') as f:
#         yaml.dump(map, yaml_file)
    
#     globimap[folder.name] = map

# glob_yaml_file = base_dir / 'toutou.yaml'
# with open(glob_yaml_file, 'w') as f:
#    yaml.dump(globimap, glob_yaml_file) 
    