
from collections import UserString

class FromAliasStr(UserString):
    def __init__(self, string: str, alias: str):
        super().__init__(string)
        self.alias = alias


_alias_strs: 'dict[str, AliasStr]' = {}


class AliasStr(UserString):
    def __new__(cls, alias: str, port_name: str) -> 'AliasStr':
        astr = _alias_strs.get(alias)
        if astr is None:
            _alias_strs[alias] = super().__new__(cls)
            return _alias_strs[alias]
        return astr
    
    def __init__(self, alias: object, port_name: str) -> None:
        super().__init__(alias)
        self.port_name = port_name
        
    def __eq__(self, string: object) -> bool:
        if isinstance(string, AliasStr):
            return super().__eq__(string)
        if isinstance(string, str):
            return self.port_name == string
        return super().__eq__(string)

    def __hash__(self) -> int:
        return hash(str())
        # return hash(self)

port_from = 'system:capture_1'
port_to = AliasStr('playback1', 'system:playback_1')
# port_to_2 = AliasStr('playback1', 'apzeof:foujou')


# print(f'{port_from=};{port_to=}')
# print(port_to == port_to_2)
port_to.port_name = 'systemik:poublak'
# print(port_to, port_to.port_name)
# print('portto is port_to_2', port_to is port_to_2)

troudi = dict[str, AliasStr]()
troudi[str(port_to)] = port_to
# troudi[str(port_to_2)] = port_to_2
# print('outchipa', ('system:capture_1', port_to) in {('system:capture_1', 'systemik:poublak')})

da_set = {('system:capture_1', 'systemik:poublak'),
          ('system:capture_1', 'system:playback_4'),
          ('system:capture_1', port_to)}
print('da_set', da_set)
for conn in (('system:capture_1', port_to),
             ('system:capture_1', 'systemik:poublak')):
    print(f'{conn} in da_set', conn in da_set)

port_to.port_name = 'system:playback_4'

for conn in (('system:capture_1', port_to),
             ('system:capture_1', 'systemik:poublak')):
    print(f'{conn} in da_set2', conn in da_set)