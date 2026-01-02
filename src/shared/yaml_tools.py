from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


class YamlMap:
    def __init__(self, map: CommentedMap):
        self._map = map
        
    def string(self, key: str, default='') -> str:
        value = self._map.get(key, default)
        if isinstance(value, (str, bytes, int, float, bool)):
            return str(value)
        return ''
    
    def int(self, key: str, default=0) -> int:
        value = self._map.get(key, default)
        if value is None:
            return default
        
        try:
            value_int = int(value)
        except:
            return default
        else:
            return value_int
        
    def float(self, key: str, default=0.0) -> float:
        value = self._map.get(key, default)
        if value is None:
            return default

        try:
            value_float = float(value)
        except:
            return default
        else:
            return value_float
        
    def bool(self, key: str, default=False) -> bool:
        value = self._map.get(key, default)
        if value is None:
            return default

        try:
            value_bool = bool(value)
        except:
            return default
        else:
            return value_bool
        
    def str_list(self, key: str) -> list[str]:
        value = self._map.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, str)]
        if isinstance(value, str):
            return [value]
        return []
    
    def map(self, key: str) -> 'YamlMap':
        value = self._map.get(key)
        if isinstance(value, CommentedMap):
            return YamlMap(value)
        return YamlMap(CommentedMap())
